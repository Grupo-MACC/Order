import asyncio
import json
import logging
from aio_pika import connect_robust, Message, ExchangeType
from services import order_service
from broker.setup_rabbitmq import RABBITMQ_HOST, EXCHANGE_NAME

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
    
    await order_paid_queue.bind(EXCHANGE_NAME, routing_key="payment.paid")
    await order_failed_queue.bind(EXCHANGE_NAME, routing_key="payment.failed")

    await order_paid_queue.consume(handle_payment_paid)
    await order_failed_queue.consume(handle_payment_failed)

    logger.info("[ORDER] 🟢 Escuchando eventos de pago...")
    await asyncio.Future()  # nunca termina, mantiene el loop activo

async def publish_order_created(order_id):
    connection = await connect_robust(RABBITMQ_HOST)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(EXCHANGE_NAME, ExchangeType.TOPIC, durable=True)
    await exchange.publish(
        Message(body=json.dumps({"order_id": order_id}).encode()),
        routing_key="order.created"
    )
    logger.info(f"[ORDER] 📤 Publicado evento order.created → {order_id}")
    await connection.close()
