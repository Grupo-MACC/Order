import pika

RABBITMQ_HOST = "rabbitmq"
EXCHANGE_NAME = "order_payment_exchange"

def setup_rabbitmq():
    #Establece conexion con el server
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()

    #Creamos el topic es decir el exchange
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)

    #Declaramos 2 colas para los pagos
    channel.queue_declare(queue='order_paid_queue', durable=True)
    channel.queue_declare(queue='order_failed_queue', durable=True)

    #Asociamos la cola a una ruta del exchange
    channel.queue_bind(exchange=EXCHANGE_NAME, queue='order_paid_queue', routing_key='payment.paid')
    channel.queue_bind(exchange=EXCHANGE_NAME, queue='order_failed_queue', routing_key='payment.failed')

    connection.close()