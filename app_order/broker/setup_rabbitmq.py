from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange

async def setup_rabbitmq():
    """
    Configura RabbitMQ creando el exchange y las colas necesarias
    usando aio_pika (asíncrono).
    """
    connection, channel = await get_channel()
    
    exchange = await declare_exchange(channel)

    # Crear colas
    order_paid_queue = await channel.declare_queue("order_paid_queue", durable=True)
    order_failed_queue = await channel.declare_queue("order_failed_queue", durable=True)
    delivery_ready_queue = await channel.declare_queue("delivery_ready_queue", durable=True)
    pieces_done_queue = await channel.declare_queue("pieces_done_queue", durable=True)    # la consumirá ORDER
    piece_date_queue = await channel.declare_queue("piece_date_queue", durable=True)    # la consumirá MACHINE

    # Enlazar colas con el exchange
    await order_paid_queue.bind(exchange, routing_key="payment.paid")
    await order_failed_queue.bind(exchange, routing_key="payment.failed")
    await delivery_ready_queue.bind(exchange, routing_key="delivery.ready")
    await pieces_done_queue.bind(exchange, routing_key="piece.done")
    await piece_date_queue.bind(exchange, routing_key="piece.date")


    print("✅ RabbitMQ configurado correctamente (exchange + colas creadas).")

    await connection.close()