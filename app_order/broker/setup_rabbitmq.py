from aio_pika import connect_robust, ExchangeType

RABBITMQ_HOST = "amqp://guest:guest@rabbitmq/"
ORDER_PAYMENT_EXCHANGE_NAME = "order_payment_exchange"
AUTH_RUNNING_EXCHANGE_NAME = "auth_active_exchange"

async def setup_rabbitmq():
    """
    Configura RabbitMQ creando el exchange y las colas necesarias
    usando aio_pika (asíncrono).
    """
    # Conexión robusta con RabbitMQ
    connection = await connect_robust(RABBITMQ_HOST)
    channel = await connection.channel()

    # Crear el exchange tipo 'topic'
    exchange = await channel.declare_exchange(
        ORDER_PAYMENT_EXCHANGE_NAME,
        ExchangeType.TOPIC,
        durable=True
    )
    
    exchange_auth = await channel.declare_exchange(
        AUTH_RUNNING_EXCHANGE_NAME,
        ExchangeType.DIRECT,
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
    
    await auth_running_queue.bind(exchange_auth, routing_key="auth.running")
    await auth_not_running_queue.bind(exchange_auth, routing_key="auth.not_running")

    print("✅ RabbitMQ configurado correctamente (exchange + colas creadas).")

    await connection.close()