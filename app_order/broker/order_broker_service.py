import pika
import json
from broker.setup_rabbitmq import EXCHANGE_NAME, RABBITMQ_HOST
import threading

def publish_order_created(order_id):
    #Abre conexion con el host
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    #Se conecta al cana
    channel = connection.channel()
    message = {"order_id": order_id}
    channel.basic_publish(
        exchange=EXCHANGE_NAME,
        routing_key='order.created',
        body=json.dumps(message)
    )
    print(f"[ORDER] 📤 Publicado evento order.created → {order_id}")
    connection.close()

def handle_payment_paid(ch, method, properties, body):
    data = json.loads(body)
    print(f"[ORDER] ✅ Pago confirmado para orden: {data['order_id']} — iniciando fabricación...")

def handle_payment_failed(ch, method, properties, body):
    data = json.loads(body)
    print(f"[ORDER] ❌ Pago fallido para orden: {data['order_id']} — cancelando...")

def consume_payment_events():
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()

    channel.basic_consume(queue='order_paid_queue', on_message_callback=handle_payment_paid, auto_ack=True)
    channel.basic_consume(queue='order_failed_queue', on_message_callback=handle_payment_failed, auto_ack=True)

    print("[ORDER] 🟢 Escuchando eventos de pago...")
    channel.start_consuming()

def start_order_broker_service():
    t = threading.Thread(target=consume_payment_events, daemon=True)
    t.start()
    print("[PAYMENT BROKER] 🚀 Servicio de RabbitMQ lanzado en background")