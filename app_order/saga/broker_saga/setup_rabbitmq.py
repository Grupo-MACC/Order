from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange_command, declare_exchange_saga

async def setup_rabbitmq():
    """
    Configura RabbitMQ creando el exchange y las colas necesarias
    usando aio_pika (asíncrono).
    """
    connection, channel = await get_channel()
    
    exchange_command = await declare_exchange_command(channel)
    exchange_saga = await declare_exchange_saga(channel)
    # Crear colas
    payment_result_queue = await channel.declare_queue("payment_result_queue", durable=True)
    delivery_result_queue = await channel.declare_queue("delivery_result_queue", durable=True)
    money_returned_queue = await channel.declare_queue("money_returned_queue", durable=True)

    # Enlazar colas con el exchange
    await payment_result_queue.bind(exchange_saga, routing_key="payment.result")
    await delivery_result_queue.bind(exchange_saga, routing_key="delivery.result")
    await money_returned_queue.bind(exchange_saga, routing_key="money.returned")

    print("✅ RabbitMQ configurado correctamente (exchange + colas creadas).")

    await connection.close()