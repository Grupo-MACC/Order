from my_states import Pending
import json
import logging
from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange_command, declare_exchange_saga, declare_exchange
from aio_pika import Message
from services import order_service

logger = logging.getLogger(__name__)

# OrderSaga (orquestador): Ejecuta las acciones, se hace aqui y no en los estados ya que los estados
# solo definen la logica de transicion entre estados.
# La saga es quien conoce los servicios de BD y Broker.
# Publica mensaje
# Escucha respuestas
# Persiste en BD

class OrderSaga(object):
    """ 
    Saga que orquesta el proceso completo de una orden.
    Maneja la comunicación entre microservicios a través de eventos.
    
    FLUJO GENERAL:
    1. Se crea OrderSaga → __init__
    2. Recibe evento del broker → on_event()
    3. Delega al estado actual → state.on_event()
    4. Estado retorna nuevo estado → on_event() actualiza
    5. Se persiste en BD → _persist_state()
    """

    def __init__(self, order_id):
        """ 
        PASO 1: Constructor - Se ejecuta UNA sola vez al crear la saga
        
        Args:
            order_id: ID única de la orden
            db_service: Servicio de base de datos
            broker_service: Servicio de mensajería (RabbitMQ, Kafka, etc)
        """
        self.order_id = order_id

        
        # Comenzar en estado Pending (SIEMPRE comienza aquí)
        self.state = Pending()
        # → Aquí se ejecuta Pending.__init__() → imprime "Processing current state: Pending"
        
        # Guardar orden inicial en BD (estado = Pending)
        self._persist_state()
        # → Guarda: order_id + estado "Pending" en la base de datos

    def _persist_state(self):
        """
        FUNCIÓN AUXILIAR: Guarda el state actual en la BD
        Se llama cada vez que el estado cambia.
        
        Responsabilidad: Persistir los cambios
        """
        # db_service.save_order(order_id=self.order_id, state=str(self.state))
        # Descommentado: guarda en BD el order_id y el nombre del estado actual
        pass

    async def on_event(self, event):
        """
        PASO 2: Se ejecuta cuando llega un evento del broker

        FLUJO AQUÍ:
        - Recibe evento (ej: {'type': 'payment_accepted', ...})
        - Delega al estado actual para procesar
        - Si el estado cambió, actualiza, persiste y dispara lógica del nuevo estado

        Args:
            event: Diccionario con el evento del broker
                Ej: {'type': 'payment_accepted', 'order_id': '123'}
        """
        print(f"📨 Evento recibido por Saga: {event}")

        # Delegar al estado ACTUAL (self.state) para que procese el evento
        # → Llama a Pending.on_event(event, self) o Paid.on_event(), etc.
        # → Retorna un NUEVO estado (puede ser el mismo o diferente)
        new_state = await self.state.on_event(event, self)

        # Comparar: ¿cambió el estado?
        if new_state.__class__ != self.state.__class__:
            # ✅ SÍ CAMBIÓ → Actualizar la referencia
            old_state_name = self.state.__class__.__name__
            new_state_name = new_state.__class__.__name__

            self.state = new_state
            print(f"🔁 Transición de estado: {old_state_name} → {new_state_name}")

            # ✅ Persistir el cambio en BD
            await self._persist_state()
            print(f"💾 Estado '{new_state_name}' guardado en base de datos.")

            # ✅ Ejecutar automáticamente la lógica de entrada del nuevo estado
            #    Ejemplo: si el nuevo estado es Paid → llama on_event({"type": "paid"})
            entry_event_type = new_state_name.lower()
            print(f"⚙️  Ejecutando lógica inicial de {new_state_name}...")
            await self.on_event({"type": entry_event_type})

        else:
            # No cambió el estado → solo log
            print(f"⏸ Estado sin cambios: {self.state.__class__.__name__}")
    

    async def publish_payment_command(self, order_data):
        """
        Se llama desde Pending.on_event() cuando llega 'order_created'
        
        Responsabilidad: Publicar mensaje al broker para que Payment lo procese
        
        FLUJO:
        Pending recibe 'order_created' 
            → publica mensaje en exchange 'command' con routing_key 'pay'
            → Payment microservicio recibe y procesa el pago
            → Payment publica resultado en exchange 'saga'
        
        Args:
            order_data: Diccionario con datos de la orden
        """
        connection, channel = await get_channel()
        exchange = await declare_exchange_command(channel)
        
        await exchange.publish(
            Message(
                body=json.dumps({
                    "order_id": self.order_id,
                    "user_id": order_data.get("user_id"),
                    "message": "Pay order"
                }).encode()
            ),
            routing_key="pay"
        )
        
        logger.info(f"[ORDER] 📤 Enviando orden {self.order_id} a pago...")

    async def listen_payment_result(self):
        """
        Se llama desde Pending.on_event() después de publish_payment_command()
        
        Responsabilidad: Escuchar la respuesta de Payment en el broker
        
        FLUJO:
        - Se suscribe a exchange 'saga' en cola 'payment_result'
        - Cuando Payment publica (payment_accepted o payment_rejected)
        - Se ejecuta callback self.on_event()
        """
        _, channel = await get_channel()
        exchange = await declare_exchange_saga(channel)
        
        queue = await channel.declare_queue("payment_result_queue", durable=True)
        await queue.bind(exchange, routing_key="payment.result")
        await queue.consume(self._handle_payment_result)
        
        logger.info(f"[ORDER] 🟢 Escuchando resultados de pago para orden {self.order_id}...")
    
    async def _handle_payment_result(self, message):
        async with message.process():
            data = json.loads(message.body)
            status = data.get("status")

            # Traducimos el mensaje del microservicio a un evento interno
            if status == "paid":
                event = {
                    "type": "payment_accepted",
                    "order_id": data["order_id"]
                }
            elif status == "not_paid":
                event = {
                    "type": "payment_rejected",
                    "order_id": data["order_id"]
                }
            else:
                print(f"⚠️ Estado desconocido del pago: {status}")
                return  # ignoramos mensajes no válidos

            # Pasamos el evento al motor de la saga
            await self.on_event(event)

    async def publish_delivery_check_command(self, order_data):
        """
        Se llama desde Paid.on_event() cuando cambias a estado Paid
        
        Responsabilidad: Publicar comando de verificación de entrega
        
        FLUJO:
        - Publica en exchange 'command' con routing_key 'check_delivery'
        - Servicio de Delivery verifica si es posible entregar
        - Publica resultado en exchange 'saga'
        
        Args:
            order_data: Diccionario con datos de la orden (incluye dirección, etc)
        """
        connection, channel = await get_channel()
        exchange = await declare_exchange_command(channel)
        
        await exchange.publish(
            Message(
                body=json.dumps({
                    "order_id": self.order_id,
                    "user_id": order_data.get("user_id"),
                    "address": order_data.get("address")
                }).encode()
            ),
            routing_key="check.delivery"
        )
        
        logger.info(f"[ORDER] 📤 Verificando entrega para orden {self.order_id}...")

    async def listen_delivery_result(self):
        """
        Se llama desde Paid.on_event() después de publish_delivery_check_command()
        
        Responsabilidad: Escuchar la respuesta del check de delivery
        
        FLUJO:
        - Se suscribe a exchange 'saga' en cola 'delivery_result'
        - Cuando Delivery publica (delivery_possible o delivery_not_possible)
        - Se ejecuta callback self.on_event()
        """
        _, channel = await get_channel()
        exchange = await declare_exchange_saga(channel)
        
        queue = await channel.declare_queue("delivery_result_queue", durable=True)
        await queue.bind(exchange, routing_key="delivery.result")
        await queue.consume(self._handle_delivery_result)
        
        logger.info(f"[ORDER] 🟢 Escuchando resultados de entrega para orden {self.order_id}...")
    
    async def _handle_delivery_result(self, message):
        async with message.process():
            data = json.loads(message.body)
            status = data.get("status")

            # Traducimos el mensaje del microservicio a un evento interno
            if status == "deliverable":
                event = {
                    "type": "delivery_possible",
                    "order_id": data["order_id"]
                }
            elif status == "not_deliverable":
                event = {
                    "type": "delivery_not_possible",
                    "order_id": data["order_id"]
                }
            else:
                print(f"⚠️ Estado desconocido del pago: {status}")
                return  # ignoramos mensajes no válidos

            # Pasamos el evento al motor de la saga
            await self.on_event(event)

    async def publish_return_money_command(self, order_data):
        """
        Se llama desde NotDeliverable.on_event() cuando la entrega no es posible
        
        Responsabilidad: Publicar comando para devolver el dinero
        
        FLUJO:
        - Publica en exchange 'command' con routing_key 'return_money'
        - Payment microservicio recibe y devuelve el dinero
        - Payment publica confirmación en exchange 'saga'
        """
        connection, channel = await get_channel()
        exchange = await declare_exchange_command(channel)
        
        await exchange.publish(
            Message(
                body=json.dumps({
                    "order_id": self.order_id,
                    "user_id": order_data.get("user_id"),
                    "amount": order_data.get("amount")
                }).encode()
            ),
            routing_key="return.money"
        )
        
        logger.info(f"[ORDER] 📤 Solicitando devolución de dinero para orden {self.order_id}...")

    async def publish_event(self, routing_key: str, body: str):
        """
        Publica un evento en el exchange principal del broker.
        """
        _, channel = await get_channel()
        exchange = await declare_exchange(channel)
        await exchange.publish(
            message=Message(body=body.encode()),
            routing_key=routing_key
        )

    async def listen_money_returned(self):
        """
        Se llama desde NotDeliverable.on_event() después de publish_return_money_command()
        
        Responsabilidad: Escuchar confirmación de devolución de dinero
        
        FLUJO:
        - Se suscribe a exchange 'saga' en cola 'money_returned'
        - Cuando Payment confirma que devolvió el dinero
        - Se ejecuta callback self.on_event()
        """
        _, channel = await get_channel()
        exchange = await declare_exchange_saga(channel)
        
        queue = await channel.declare_queue("money_returned_queue", durable=True)
        await queue.bind(exchange, routing_key="money.returned")
        await queue.consume(self._handle_money_returned)
        
        logger.info(f"[ORDER] 🟢 Escuchando confirmación de devolución de dinero para orden {self.order_id}...")
    
    async def _handle_money_returned(self, message):
        async with message.process():
            data = json.loads(message.body)
            await self.on_event({
                "type": "money_returned",
                "order_id": data["order_id"]
            })
        # broker_service.subscribe(
        #     exchange='saga',
        #     queue='money_returned',
        #     callback=self.on_event
        # )
        pass

    async def _handle_money_result(self, message):
        async with message.process():
            data = json.loads(message.body)
            event = {
                "type": "money_returned",
                "order_id": data["order_id"]
            }

            # Pasamos el evento al motor de la saga
            await self.on_event(event)