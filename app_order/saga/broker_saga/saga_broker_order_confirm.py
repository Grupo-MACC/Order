import json
import logging
from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange_command, declare_exchange_saga
from aio_pika import Message

logger = logging.getLogger(__name__)

async def publish_payment_command(order_data):
    _, channel = await get_channel()
    exchange = await declare_exchange_command(channel)
        
    await exchange.publish(
        Message(
            body=json.dumps({
                "order_id": order_data.id,
                "user_id": order_data.user_id,
                "number_of_pieces": order_data.number_of_pieces,
                "message": "Pay order"
            }).encode()
        ),
        routing_key="pay"
    )
        
    logger.info(f"[ORDER] 📤 Enviando orden {order_data.id} a pago...")
    
async def publish_delivery_check_command(order_data):
    _, channel = await get_channel()
    exchange = await declare_exchange_command(channel)
        
    await exchange.publish(
        Message(
            body=json.dumps({
                "order_id": order_data.id,
                "user_id": order_data.user_id,
                "address": order_data.address
            }).encode()
        ),
        routing_key="check.delivery"
    )
        
    logger.info(f"[ORDER] 📤 Verificando entrega para orden {order_data.id}...")

async def publish_return_money_command(order_data):
    _, channel = await get_channel()
    exchange = await declare_exchange_command(channel)
        
    await exchange.publish(
        Message(
            body=json.dumps({
                "order_id": order_data.id,
                "user_id": order_data.user_id
            }).encode()
        ),
        routing_key="return.money"
    )
        
    logger.info(f"[ORDER] 📤 Solicitando devolución de dinero para orden {order_data.id}...")


async def handle_payment_result(message):
    async with message.process():
        data = json.loads(message.body)
        status = data.get("status")
        order_id = data.get("order_id")

            # Traducimos el mensaje del microservicio a un evento interno
        if status == "paid":
            event = {
                "type": "payment_accepted"
            }
        elif status == "not_paid":
            event = {
                "type": "payment_rejected"
            }
        else:
            print(f"⚠️ Estado desconocido del pago: {status}")
            return  # ignoramos mensajes no válidos

            # Pasamos el evento al motor de la saga
        from saga.state_machine.order_confirm_saga_manager import saga_manager
        saga = saga_manager.get_saga(order_id)
        await saga.on_event_saga(event)

async def handle_delivery_result(message):
    async with message.process():
        data = json.loads(message.body)
        status = data.get("status")
        order_id = data.get("order_id")

            # Traducimos el mensaje del microservicio a un evento interno
        if status == "deliverable":
            event = {
                "type": "delivery_possible"
            }
        elif status == "not_deliverable":
            event = {
                "type": "delivery_not_possible"
            }
        else:
            print(f"⚠️ Estado desconocido del pago: {status}")
            return  # ignoramos mensajes no válidos

        from saga.state_machine.order_confirm_saga_manager import saga_manager
        saga = saga_manager.get_saga(order_id)
        await saga.on_event_saga(event)

async def handle_money_returned(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data.get("order_id")
        from saga.state_machine.order_confirm_saga_manager import saga_manager
        saga = saga_manager.get_saga(order_id = data.get("order_id"))
        await saga.on_event_saga({
            "type": "money_returned"
        })

async def listen_payment_result():
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)
        
    queue = await channel.declare_queue("payment_result_queue", durable=True)
    await queue.bind(exchange, routing_key="payment.result")
    await queue.consume(handle_payment_result)
        
    logger.info(f"[ORDER] 🟢 Escuchando resultados de pago")

async def listen_delivery_result():
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)
        
    queue = await channel.declare_queue("delivery_result_queue", durable=True)
    await queue.bind(exchange, routing_key="delivery.result")
    await queue.consume(handle_delivery_result)
        
    logger.info(f"[ORDER] 🟢 Escuchando resultados de entrega")

async def listen_money_returned_result():
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)
        
    queue = await channel.declare_queue("money_returned_queue", durable=True)
    await queue.bind(exchange, routing_key="money.returned")
    await queue.consume(handle_money_returned)
        
    logger.info(f"[ORDER] 🟢 Escuchando confirmación de devolución de dinero")