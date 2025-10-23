from aio_pika import connect_robust, ExchangeType
from core.config import settings

async def setup_rabbitmq():
    """
    Configura RabbitMQ creando el exchange y las colas necesarias
    usando aio_pika (asíncrono).
    """
    # Conexión robusta con RabbitMQ
    connection = await connect_robust(settings.RABBITMQ_HOST)
    channel = await connection.channel()
    # Crear el exchange tipo 'topic'
    exchange = await channel.declare_exchange(
        settings.EXCHANGE_NAME,
        ExchangeType.TOPIC,
        durable=True
    )

    # Crear colas
    order_paid_queue = await channel.declare_queue("order_paid_queue", durable=True)
    order_failed_queue = await channel.declare_queue("order_failed_queue", durable=True)

    # Enlazar colas con el exchange
    await order_paid_queue.bind(exchange, routing_key="payment.paid")
    await order_failed_queue.bind(exchange, routing_key="payment.failed")
    
    auth_running_queue = await channel.declare_queue("auth_running_queue", durable=True)
    auth_not_running_queue = await channel.declare_queue("auth_not_running_queue", durable=True)
    
    await auth_running_queue.bind(exchange, routing_key="auth.running")
    await auth_not_running_queue.bind(exchange, routing_key="auth.not_running")

    print("✅ RabbitMQ configurado correctamente (exchange + colas creadas).")

    await connection.close()