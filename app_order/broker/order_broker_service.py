import asyncio
import json
import logging
import httpx
from aio_pika import connect_robust, Message, ExchangeType
from services import order_service
from broker.setup_rabbitmq import RABBITMQ_HOST, ORDER_PAYMENT_EXCHANGE_NAME, AUTH_RUNNING_EXCHANGE_NAME
from routers.router_utils import AUTH_SERVICE_URL
from core.security import PUBLIC_KEY_PATH

logger = logging.getLogger(__name__)

async def handle_payment_paid(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]

        db_order = await order_service.update_order_status(order_id=order_id, status="PAID")
        print(db_order)
        logger.info(f"[ORDER] ✅ Pago confirmado para orden: {order_id}")

async def handle_payment_failed(message):
    async with message.process():
        data = json.loads(message.body)
        logger.info(f"[ORDER] ❌ Pago fallido para orden: {data}")

async def consume_payment_events():
    connection = await connect_robust(RABBITMQ_HOST)
    channel = await connection.channel()
    
    order_paid_queue = await channel.declare_queue("order_paid_queue", durable=True)
    order_failed_queue = await channel.declare_queue("order_failed_queue", durable=True)
    
    await order_paid_queue.bind(ORDER_PAYMENT_EXCHANGE_NAME, routing_key="payment.paid")
    await order_failed_queue.bind(ORDER_PAYMENT_EXCHANGE_NAME, routing_key="payment.failed")

    await order_paid_queue.consume(handle_payment_paid)
    await order_failed_queue.consume(handle_payment_failed)

    logger.info("[ORDER] 🟢 Escuchando eventos de pago...")
    await asyncio.Future()
    
async def handle_auth_running(message):
    """Se ejecuta cuando el servicio Auth está 'running'."""
    async with message.process():
        data = json.loads(message.body)
        if data["service"] == "auth" and data["status"] == "running":
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{AUTH_SERVICE_URL}/auth/public-key"
                    )
                    response.raise_for_status()
                    public_key = response.text
                    
                    with open(PUBLIC_KEY_PATH, "w", encoding="utf-8") as f:
                        f.write(public_key)
                        
                    logger.info(f"✅ Clave pública de Auth guardada en {PUBLIC_KEY_PATH}")
            except Exception as exc:
                logger.error(f"Error obteniendo clave pública de Auth: {exc}")
                
    
async def handle_auth_not_running(message):
    """Se ejecuta cuando el servicio Auth está 'not_running'."""
    async with message.process():
        data = json.loads(message.body)

        if data.get("service") == "auth" and data.get("status") == "not_running":
            try:
                # 🚫 Invalidar la clave pública (por ejemplo, eliminarla)
                import os
                if os.path.exists(PUBLIC_KEY_PATH):
                    os.remove(PUBLIC_KEY_PATH)
                    logger.info("Clave pública eliminada (Auth no está activo).")
                else:
                    logger.warning("No se encontró la clave pública para eliminar.")
            except Exception as exc:
                logger.error(f"Error al eliminar clave pública: {exc}")
        

async def consume_auth_events():
    connection = await connect_robust(RABBITMQ_HOST)
    channel = await connection.channel()
    
    auth_running_queue = await channel.declare_queue("auth_running_queue", durable=True)
    auth_not_running_queue = await channel.declare_queue("auth_not_running_queue", durable=True)
    
    await auth_running_queue.bind(AUTH_RUNNING_EXCHANGE_NAME, routing_key="auth.running")
    await auth_not_running_queue.bind(AUTH_RUNNING_EXCHANGE_NAME, routing_key="auth.not_running")
    
    await auth_running_queue.consume(handle_auth_running)
    await auth_not_running_queue.consume(handle_auth_not_running)

async def publish_order_created(order_id):
    connection = await connect_robust(RABBITMQ_HOST)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(ORDER_PAYMENT_EXCHANGE_NAME, ExchangeType.TOPIC, durable=True)
    await exchange.publish(
        Message(body=json.dumps({"order_id": order_id}).encode()),
        routing_key="order.created"
    )
    logger.info(f"[ORDER] 📤 Publicado evento order.created → {order_id}")
    await connection.close()


async def handle_machine_job_completed(message):
    async with message.process():  # ack automático si no falla
        print("[ORDER] handler called!")   # <<-- AÑADIR
        data = json.loads(message.body)
        print("[ORDER] payload:", data)    # <<-- 
        
        try:
            data = json.loads(message.body)
        except Exception:
            logger.exception("[ORDER] ❌ Mensaje inválido en machine.job.completed")
            return

        order_id = data.get("order_id")
        piece_ids = data.get("piece_ids", [])

        logger.info(f"[ORDER] 📥 machine.job.completed recibido order={order_id} pieces={piece_ids}")

        # 🔧 Aquí actualizas el estado del pedido a DONE (o Finished) con tu lógica
        try:
            # Si tienes un servicio interno:
            # from services.order_service import update_order_status
            # await update_order_status(order_id=order_id, status="DONE")

            # Por ahora, solo logueamos como prueba:
            logger.info(f"[ORDER] ✅ Order {order_id} DONE (machine.job.completed)")
        except Exception as e:
            logger.exception(f"[ORDER] ❌ Error marcando DONE order={order_id}: {e}")


# --- Machine-order
RABBITMQ_HOST_PLANT = "amqp://guest:guest@rabbitmq/"
PLANT_EXCHANGE_NAME = "plant.events"

async def consume_machine_events():
    """
    Order escucha machine.job.completed de Machine.
    Declara la cola 'order_machine_completed_queue' y la bindea al exchange 'plant.events'
    con la routing_key 'machine.job.completed'.
    """
    print("[ORDER] starting consume_machine_events()")   # <<--

    connection = await connect_robust(RABBITMQ_HOST_PLANT)
    channel = await connection.channel()

    exchange = await channel.declare_exchange(PLANT_EXCHANGE_NAME, ExchangeType.TOPIC, durable=True)

    queue = await channel.declare_queue("order_machine_completed_queue", durable=True)
    await queue.bind(exchange, routing_key="machine.job.completed")

    await queue.consume(handle_machine_job_completed)
    logger.info("[ORDER] 🟢 Escuchando machine.job.completed …")
    
    print("[ORDER] listening machine.job.completed ...")   # <<--

    # Mantener viva la tarea
    await asyncio.Future()