import asyncio
import httpx
import json
import logging
from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange, PUBLIC_KEY_PATH, declare_exchange_logs
from aio_pika import Message
from services import order_service
from consul_client import get_service_url
import os
from sql import models 

logger = logging.getLogger(__name__)


def _normalize_mfg_status(raw: str) -> str:
    """
    Normaliza strings de estado que puedan venir desde Warehouse.

    Ejemplos aceptados:
        - "requested", "Requested"
        - "in_progress", "inprogress", "InProgress"
        - "completed", "done"
        - "failed", "error"
    """
    if not raw:
        return models.Order.MFG_FAILED

    s = str(raw).strip().lower()

    if s in {"requested", "queued"}:
        return models.Order.MFG_REQUESTED
    if s in {"inprogress", "in_progress", "working", "processing"}:
        return models.Order.MFG_IN_PROGRESS
    if s in {"completed", "done", "finished"}:
        return models.Order.MFG_COMPLETED
    if s in {"failed", "error"}:
        return models.Order.MFG_FAILED

    # Si llega algo raro, mejor marcar failed o dejar log.
    return models.Order.MFG_FAILED

#region payment
async def handle_payment_paid(message):
    """
    LEGACY: si se usa payment.paid/payment.failed fuera de la saga.
    No dispara fabricación. Solo actualiza creation_status.
    """
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]

        await order_service.update_order_creation_status(order_id=order_id, status=models.Order.CREATION_PAID)
        logger.info("[ORDER] (legacy) payment.paid → order=%s", order_id)


async def handle_payment_failed(message):
    async with message.process():
        data = json.loads(message.body)
        error_message = data["message"]
        order_id = data["order_id"]
        status = data["status"]
        logger.info(f"message: {error_message}")
        logger.info(f"[ORDER] ❌ Pago fallido para orden: {data}")
        await publish_to_logger(message={"message":f"Pago fallido para orden: {data}!❌"},topic="order.error")
        db_order = await order_service.update_order_status(order_id=order_id, status=status)

async def consume_payment_events():
    _, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    
    order_paid_queue = await channel.declare_queue("order_paid_queue", durable=True)
    order_failed_queue = await channel.declare_queue("order_failed_queue", durable=True)
    
    await order_paid_queue.bind(exchange, routing_key="payment.paid")
    await order_failed_queue.bind(exchange, routing_key="payment.failed")

    await order_paid_queue.consume(handle_payment_paid)
    await order_failed_queue.consume(handle_payment_failed)

    logger.info("[ORDER] 🟢 Escuchando eventos de pago...")
    await asyncio.Future()

#region order created
async def publish_order_created(order_id, number_of_pieces, user_id):
    connection, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    await exchange.publish(
        Message(body=json.dumps({"order_id": order_id, "number_of_pieces": number_of_pieces, "user_id": user_id, "message": "Orden creada"}).encode()),
        routing_key="order.created"
    )
    logger.info(f"[ORDER] 📤 Publicado evento order.created → {order_id}")
    await publish_to_logger(message={"message":f"📤 Publicado evento order.created → {order_id}"},topic="order.debug")
    await connection.close()

#region delivery
async def consume_delivery_events():
    _, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    
    delivery_ready_queue = await channel.declare_queue("delivery_ready_queue", durable=True)
    
    await delivery_ready_queue.bind(exchange, routing_key="delivery.ready")

    await delivery_ready_queue.consume(handle_delivery_ready)

    logger.info("[ORDER] 🟢 Escuchando eventos de pago...")
    await publish_to_logger(message={"message":"🟢 Escuchando eventos de entrega..."},topic="order.info")
    await asyncio.Future()

async def handle_delivery_ready(message):
    """
    Actualiza el delivery_status cuando Delivery confirma que la entrega está lista/realizada.

    Nota:
        - Antes se llamaba update_order_status() (ya no existe).
        - Ahora se actualiza el campo delivery_status.
    """
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]
        status = data["status"]

        db_order = await order_service.update_order_delivery_status(order_id=order_id, status=status)
        logger.info("[ORDER] 🚚 delivery.ready → order_id=%s status=%s", order_id, status)

        await publish_to_logger(
            message={"message": f"🚚 Delivery status actualizado: order={order_id} status={status}"},
            topic="order.info",
        )


#region order
async def publish_do_order(order_id: int, number_of_pieces: int, pieces_a: int, pieces_b: int) -> None:
    """Publica el comando mínimo hacia warehouse (routing_key=order.created)."""
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange(channel)
        payload = {
            "order_id": order_id,
            "number_of_pieces": int(number_of_pieces),
            "pieces_a": int(pieces_a),
            "pieces_b": int(pieces_b),
        }
        msg = Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            headers={"event": "order.created"},
            delivery_mode=2,
        )
        await exchange.publish(msg, routing_key="order.created")
        logger.info("[ORDER] 📤 order.created → %s", payload)
    finally:
        await connection.close()

#region auth
async def consume_auth_events():
    _, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    
    order_queue = await channel.declare_queue('order_queue', durable=True)
    await order_queue.bind(exchange, routing_key="auth.running")
    await order_queue.bind(exchange, routing_key="auth.not_running")
    
    await order_queue.consume(handle_auth_events)

async def handle_auth_events(message):
    async with message.process():
        data = json.loads(message.body)
        if data["status"] == "running":
            try:
                # Use Consul to discover auth service (no fallback)
                auth_service_url = await get_service_url("auth")
                logger.info(f"[ORDER] 🔍 Auth descubierto via Consul: {auth_service_url}")
                
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{auth_service_url}/auth/public-key"
                    )
                    response.raise_for_status()
                    public_key = response.text
                    
                    with open(PUBLIC_KEY_PATH, "w", encoding="utf-8") as f:
                        f.write(public_key)
                    
                    logger.info(f"[ORDER] ✅ Clave pública de Auth guardada en {PUBLIC_KEY_PATH}")
                    await publish_to_logger(
                        message={
                            "message": "Clave pública de Auth guardada",
                            "path": PUBLIC_KEY_PATH,
                        },
                        topic="order.info",
                    )
            except Exception as exc:
                logger.error(f"[ORDER] ❌ Error obteniendo clave pública de Auth: {exc}")
                await publish_to_logger(
                    message={
                        "message": "Error obteniendo clave pública de Auth",
                        "error": str(exc),
                    },
                    topic="order.error",
                )

#region logger
async def publish_to_logger(message, topic):
    connection = None
    try:
        connection, channel = await get_channel()
        
        exchange = await declare_exchange_logs(channel)
        
        # Asegúrate de que el mensaje tenga estos campos
        log_data = {
            "measurement": "logs",
            "service": topic.split('.')[0],
            "severity": topic.split('.')[1],
            **message
        }

        msg = Message(
            body=json.dumps(log_data).encode(), 
            content_type="application/json", 
            delivery_mode=2
        )
        await exchange.publish(message=msg, routing_key=topic)
        
    except Exception as e:
        print(f"Error publishing to logger: {e}")
    finally:
        if connection:
            await connection.close()

#region warehouse
async def publish_order_to_warehouse(order_payload: dict) -> None:
    """Publica una order (completa) para que Warehouse la procese.

    Args:
        order_payload:
            Diccionario JSON con el contrato acordado, por ejemplo:
            {
              "order_id": 123,
              "order_date": "...ISO...",
              "lines":[{"piece_type":"A","quantity":2}, ...]
            }

    Notas:
        - delivery_mode=2 hace el mensaje persistente (si la cola es durable).
        - Este publisher NO declara colas. Eso debe hacerlo Warehouse en su setup.
    """
    logger.info("[ORDER] About to publish to routing_key=%s", "warehouse.order")
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange(channel)

        body = json.dumps(order_payload).encode("utf-8")
        msg = Message(
            body=body,
            content_type="application/json",
            delivery_mode=2,  # persistente
        )

        await exchange.publish(message=msg, routing_key="warehouse.order")#order.created
        logger.info("[ORDER] Published OK")

    finally:
        await connection.close()

async def consume_warehouse_events():
    """
    Declara una cola para eventos de Warehouse y los consume.

    Config:
        - WAREHOUSE_EVENTS_BINDING: binding key para el exchange (por defecto 'warehouse.#')
          Ajusta esto a lo que realmente publique Warehouse.
    """
    _, channel = await get_channel()
    exchange = await declare_exchange(channel)

    binding = os.getenv("WAREHOUSE_EVENTS_BINDING", "warehouse.#")

    queue = await channel.declare_queue("warehouse_events_queue", durable=True)
    await queue.bind(exchange, routing_key=binding)
    await queue.consume(handle_warehouse_event)

    logger.info("[ORDER] 🟢 Escuchando eventos de Warehouse con binding=%s", binding)
    await publish_to_logger(
        message={"message": f"🟢 Escuchando eventos de Warehouse ({binding})"},
        topic="order.info",
    )

    await asyncio.Future()

async def handle_warehouse_event(message):
    """
    Consume eventos emitidos por Warehouse sobre el estado de fabricación.

    Requisitos mínimos del payload:
        - order_id: int
        - status (o manufacturing_status): str
    """
    async with message.process():
        data = json.loads(message.body)

        order_id = data.get("order_id")
        raw_status = data.get("status") or data.get("manufacturing_status")

        if not order_id:
            logger.warning("[ORDER] Evento warehouse ignorado (sin order_id): %s", data)
            return

        new_status = _normalize_mfg_status(raw_status)

        db_order = await order_service.update_order_manufacturing_status(
            order_id=int(order_id),
            status=new_status,
        )

        logger.info("[ORDER] 🏭 warehouse.* → order=%s mfg_status=%s", order_id, new_status)

        # Cuando Warehouse completa, ahora sí publicamos order.created a delivery
        if db_order and new_status == models.Order.MFG_COMPLETED:
            await publish_order_created(
                order_id=db_order.id,
                number_of_pieces=db_order.number_of_pieces,
                user_id=db_order.client_id,
            )
            await publish_to_logger(
                message={"message": f"📤 order.created publicado tras fabricación: order={db_order.id}"},
                topic="order.info",
            )