import asyncio
import json
import logging
import httpx
from aio_pika import connect_robust, Message, ExchangeType
from services import order_service
from broker.setup_rabbitmq import RABBITMQ_HOST, ORDER_PAYMENT_EXCHANGE_NAME, AUTH_RUNNING_EXCHANGE_NAME
from routers.router_utils import AUTH_SERVICE_URL
#from dependencies import PUBLIC_KEY_PATH

logger = logging.getLogger(__name__)

async def handle_payment_paid(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]

        db_order = await order_service.update_order_status(order_id=order_id, status="Paid")
        #db_order = await update_order_status(order_id=order_id, status="Paid")
        try:
            piece_ids = [str(piece.id) for piece in db_order.pieces]
        except Exception as exc:
            print(exc)
        await publish_do_pieces(order_id=order_id,piece_ids=piece_ids)
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
'''
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
'''    

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

async def consume_delivery_events():
    connection = await connect_robust(RABBITMQ_HOST)
    channel = await connection.channel()
    
    delivery_ready_queue = await channel.declare_queue("delivery_ready_queue", durable=True)
    
    await delivery_ready_queue.bind(ORDER_PAYMENT_EXCHANGE_NAME, routing_key="delivery.ready")


    await delivery_ready_queue.consume(handle_delivery_ready)

    logger.info("[ORDER] 🟢 Escuchando eventos de pago...")
    await asyncio.Future()

async def handle_delivery_ready(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]
        status = data["status"]
        db_order = await order_service.update_order_status(order_id=order_id, status=status)
        print(db_order)
        logger.info(f"[ORDER] ✅ Pago confirmado para orden: {order_id}")

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
    conn = await connect_robust(RABBITMQ_HOST)
    ch   = await conn.channel()
    ex   = await ch.declare_exchange(ORDER_PAYMENT_EXCHANGE_NAME, ExchangeType.TOPIC, durable=True)
    q    = await ch.declare_queue("pieces_done_queue", durable=True)
    q2  = await ch.declare_queue("piece_date_queue", durable=True)
    await q.bind(ex, routing_key="piece.done")
    await q2.bind(ex, routing_key="piece.date")
    await q.consume(handle_pieces_done)
    await q2.consume(handle_pieces_date)
    logger.info("[ORDER] 🟢 Escuchando piece.done …")
    import asyncio; await asyncio.Future()

async def publish_do_pieces(order_id: int, piece_ids: list[str]):
    connection  = await connect_robust(RABBITMQ_HOST)
    channel     = await connection.channel()
    exchange    = await channel.declare_exchange(ORDER_PAYMENT_EXCHANGE_NAME, ExchangeType.TOPIC, durable=True)

    payload = {"order_id": order_id, "piece_ids": piece_ids}
    msg = Message(
        json.dumps(payload).encode(),
        content_type="application/json",
        headers={"event": "do.pieces"}
    )
    await exchange.publish(msg, routing_key="do.pieces")
    logger.info(f"[ORDER] 📤 machine.do_pieces → order={order_id} pieces={piece_ids}")
    await connection.close()
