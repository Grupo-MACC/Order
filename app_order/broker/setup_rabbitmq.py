import pika

RABBITMQ_HOST = ""
EXCHANGE_NAME = "order_payment_exchange"

def setup_rabbitmq():
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()

    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)

    channel.queue_declare(queue='order_paid_queue', durable=True)
    channel.queue_declare(queue='order_failed_queue', durable=True)

    channel.queue_bind(exchange=EXCHANGE_NAME, queue='order_paid_queue', routing_key='payment.paid')
    channel.queue_bind(exchange=EXCHANGE_NAME, queue='order_failed_queue', routing_key='payment.failed')

    connection.close()