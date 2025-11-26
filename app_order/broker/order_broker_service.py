import asyncio
import httpx
import json
import logging
from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange, PUBLIC_KEY_PATH, declare_exchange_logs
from aio_pika import Message
from services import order_service
from consul_client import get_service_url

logger = logging.getLogger(__name__)

async def handle_payment_paid(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]

        db_order = await order_service.update_order_status(order_id=order_id, status="Paid")
        try:
            piece_ids = [str(piece.id) for piece in db_order.pieces]
        except Exception as exc:
            print(exc)
        await publish_do_pieces(order_id=order_id,piece_ids=piece_ids)
        print(db_order)
        logger.info(f"[ORDER] ✅ Pago confirmado para orden: {order_id}")
        await publish_to_logger(message={"message":f"Pago Confirmado para orden: {order_id}!✅"},topic="order.info")

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
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]
        status = data["status"]
        db_order = await order_service.update_order_status(order_id=order_id, status=status)
        print(db_order)
        logger.info(f"[ORDER] ✅ Pago confirmado para orden: {order_id}")
        await publish_to_logger(message={"message":f"✅ Entrega confirmada para orden: {order_id}"},topic="order.info")

##Machine
async def handle_pieces_done(message):
    async with message.process():
        data = json.loads(message.body)
        #order_id  = data["order_id"]
        piece_id = data["piece_id"]
        status = data["status"]
        await order_service.update_piece_status(piece_id, status)

async def handle_pieces_date(message):
    async with message.process():
        data = json.loads(message.body)
        #order_id  = data["order_id"]
        piece_id = data["piece_id"]
        await order_service.update_piece_manufacturing_date_to_now(piece_id)

async def consume_machine_events():
    _, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    pieces_done_queue   = await channel.declare_queue("pieces_done_queue", durable=True)
    piece_date_queue  = await channel.declare_queue("piece_date_queue", durable=True)
    await pieces_done_queue.bind(exchange, routing_key="piece.done")
    await piece_date_queue.bind(exchange, routing_key="piece.date")
    await pieces_done_queue.consume(handle_pieces_done)
    await piece_date_queue.consume(handle_pieces_date)
    logger.info("[ORDER] 🟢 Escuchando piece.done …")
    await publish_to_logger(message={"message":"🟢 Escuchando eventos de machine"},topic="order.info")
    import asyncio; await asyncio.Future()

async def publish_do_pieces(order_id: int, piece_ids: list[str]):
    connection, channel = await get_channel()
    
    exchange = await declare_exchange(channel)

    payload = {"order_id": order_id, "piece_ids": piece_ids}
    msg = Message(
        json.dumps(payload).encode(),
        content_type="application/json",
        headers={"event": "do.pieces"}
    )
    await exchange.publish(msg, routing_key="do.pieces")
    logger.info(f"[ORDER] 📤 machine.do_pieces → order={order_id} pieces={piece_ids}")
    await publish_to_logger(message={"message":f"📤 machine.do_pieces → order={order_id} pieces={piece_ids}"},topic="order.debug")
    await connection.close()
    

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
                # Discover auth service via Consul
                auth_service_url = await get_service_url("auth", "https://auth:5004")
                
                async with httpx.AsyncClient(
                    verify="/certs/ca.pem",
                    cert=("/certs/order/order-cert.pem", "/certs/order/order-key.pem"),
                ) as client:
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