# my_states.py

# Qué es: Las 6 implementaciones concretas de estados
# Qué hace: Cada estado decide qué hacer cuando recibe un evento
# (ej: Pending recibe payment_accepted → retorna Paid())

from .state import State

import json


# ============================================================================
# FLUJO COMPLETO DE LA SAGA:
# 
# 1. CREAR ORDEN → Pending
#    - Publica comando de pago
#    - Escucha resultado de pago
#
# 2a. PAGO ACEPTADO → Paid
#    - Guarda estado "Paid" en BD
#    - Publica check de delivery
#    - Escucha resultado de delivery
#
# 2b. PAGO RECHAZADO → NoMoney
#    - Guarda estado "NoMoney" en BD
#    - FIN DEL FLUJO
#
# 3a. DELIVERY POSIBLE → Confirmed
#    - Guarda estado "Confirmed" en BD
#    - FIN DEL FLUJO
#
# 3b. DELIVERY NO POSIBLE → NotDeliverable
#    - Guarda estado "NotDeliverable" en BD
#    - Publica comando de devolución de dinero
#    - Escucha confirmación de devolución
#
# 4. DINERO DEVUELTO → Returned
#    - Guarda estado "Returned" en BD
#    - FIN DEL FLUJO
# ============================================================================

class Pending(State):
    """
    ESTADO 1: Inicial
    
    ¿Cuándo se crea?
    - Automáticamente cuando se crea OrderSaga
    
    ¿Qué hace?
    - Espera evento 'order_created'
    - Publica comando de pago
    - Espera respuesta (payment_accepted o payment_rejected)
    
    ¿A qué estados puede ir?
    - Paid (si payment_accepted)
    - NoMoney (si payment_rejected)
    """

    async def on_event(self, event, saga):
        """
        LÓGICA DE PENDING: ¿Qué hago con cada evento?
        """
        
        # CASO 1: Llega evento de creación de orden
        if event.get('type') == 'order_created':
            # ✓ Se ejecuta solo UNA VEZ al crear la orden
            
            # Llamar a saga para publicar comando de pago
            await saga.publish_payment_command(event.get('order_data', {}))
            # → Publica en exchange 'command' con routing_key 'pay'
            
            # Llamar a saga para escuchar resultado
            await saga.listen_payment_result()
            # → Se suscribe al exchange 'saga' en cola 'payment_result'
            # → Cuando Payment responde, el broker llama saga.on_event() automáticamente
            
            # Mantener el estado actual (Pending)
            return self
        
        # CASO 2: Pago fue ACEPTADO (respuesta de Payment)
        elif event.get('type') == 'payment_accepted':
            # ✓ Cambiar a estado Paid
            print(f"✓ Pago aceptado para orden {saga.order_id}")
            return Paid()
            # → Crea nueva instancia Paid()
            # → Se ejecuta Paid.__init__() → imprime "Processing current state: Paid"
            # → Retorna a OrderSaga.on_event()
            # → OrderSaga detecta cambio: self.state = Paid()
            # → Llama _persist_state() para guardar "Paid" en BD
        
        # CASO 3: Pago fue RECHAZADO (respuesta de Payment)
        elif event.get('type') == 'payment_rejected':
            # ✓ Cambiar a estado NoMoney
            print(f"✗ Pago rechazado para orden {saga.order_id}")
            return NoMoney()
            # → Crea nueva instancia NoMoney()
            # → Se ejecuta NoMoney.__init__()
            # → Retorna a OrderSaga.on_event()
            # → OrderSaga detecta cambio: self.state = NoMoney()
            # → Llama _persist_state() para guardar "NoMoney" en BD

        return self  # Permanecer en Pending


class Paid(State):
    """
    ESTADO 2: Pago aceptado
    
    ¿Cuándo se crea?
    - Cuando llega evento 'payment_accepted' estando en Pending
    
    ¿Qué hace?
    - Guarda estado en BD
    - Publica comando de verificación de entrega
    - Espera respuesta (delivery_possible o delivery_not_possible)
    
    ¿A qué estados puede ir?
    - Confirmed (si delivery_possible)
    - NotDeliverable (si delivery_not_possible)
    """

    async def on_event(self, event, saga):
        """
        LÓGICA DE PAID: ¿Qué hago con cada evento?
        
        En este estado, la orden está pagada, verificamos si se puede entregar.
        """
        
        # CASO 1: Orden creada → Verificar entrega
        if event.get('type') == 'paid':
            # ✓ Se ejecuta cuando se entra en este estado
            
            # Llamar a saga para publicar check de delivery
            await saga.publish_delivery_check_command(event.get('order_data', {}))
            # → Publica en exchange 'command' con routing_key 'check_delivery'
            
            # Llamar a saga para escuchar resultado
            await saga.listen_delivery_result()
            # → Se suscribe al exchange 'saga' en cola 'delivery_result'
            # → Cuando Delivery responde, el broker llama saga.on_event() automáticamente
            
            return self
        
        # CASO 2: Entrega es POSIBLE
        elif event.get('type') == 'delivery_possible':
            # ✓ Cambiar a estado Confirmed
            print(f"✓ Entrega posible para orden {saga.order_id}")
            return Confirmed()
            # → Crea nueva instancia Confirmed()
            # → Se ejecuta Confirmed.__init__()
            # → Retorna a OrderSaga.on_event()
            # → OrderSaga detecta cambio: self.state = Confirmed()
            # → Llama _persist_state() para guardar "Confirmed" en BD
        
        # CASO 3: Entrega NO es POSIBLE
        elif event.get('type') == 'delivery_not_possible':
            # ✓ Cambiar a estado NotDeliverable
            print(f"✗ Entrega no posible para orden {saga.order_id}")
            return NotDeliverable()
            # → Crea nueva instancia NotDeliverable()
            # → Se ejecuta NotDeliverable.__init__()
            # → Retorna a OrderSaga.on_event()
            # → OrderSaga detecta cambio: self.state = NotDeliverable()
            # → Llama _persist_state() para guardar "NotDeliverable" en BD

        return self  # Permanecer en Paid


class Confirmed(State):
    """
    ESTADO 3: Orden confirmada y entrega posible
    
    ¿Cuándo se crea?
    - Cuando Delivery confirma que la entrega es posible
    
    ¿Qué hace?
    - Guarda estado "Confirmed" en BD
    - FIN DEL FLUJO
    """

    async def on_event(self, event, saga):
        """
        LÓGICA DE CONFIRMED: Estado final de éxito
        
        En este punto la orden está lista para ser entregada.
        No necesitamos hacer nada más en la saga.
        """
        event_type = event.get("type")

        # CASO: Entramos al estado Confirmed
        if event_type == "confirmed":
            print(f"✅ Orden {saga.order_id} confirmada. Publicando evento 'payment.paid'...")

            # Publicar evento final al broker
            await saga.publish_event(
                routing_key="payment.paid",
                body=json.dumps({
                    "order_id": saga.order_id,
                    "status": "Paid",
                    "message": "Order confirmed and ready for delivery"
                })
            )

            print(f"📤 Evento 'payment.paid' publicado con éxito en el exchange broker.")
            return self
        # En este estado, simplemente permanecemos
        # El sistema de delivery continuará desde aquí
        return self


class NoMoney(State):
    """
    ESTADO 4: Pago rechazado - sin dinero
    
    ¿Cuándo se crea?
    - Cuando Payment rechaza el pago estando en Pending
    
    ¿Qué hace?
    - Guarda estado "NoMoney" en BD
    - FIN DEL FLUJO
    """

    async def on_event(self, event, saga):
        """
        LÓGICA DE NOMONEY: El pago fue rechazado
        
        Aquí termina el flujo de la saga. La orden no puede continuar.
        """
        event_type = event.get("type")

        # CASO: Entramos al estado NoMoney
        if event_type == "nomoney":
            print(f"✗ Orden {saga.order_id} sin dinero. Publicando evento 'payment.rejected'...")

            # Publicar evento final al broker
            await saga.publish_event(
                routing_key="payment.failed",
                body=json.dumps({
                    "order_id": saga.order_id,
                    "status": "Not Paid",
                    "message": "Order not paid due to insufficient funds"
                })
            )

            print(f"📤 Evento 'payment.failed' publicado con éxito en el exchange broker.")
            return self
        
        # En este estado, la orden no puede continuar
        # Simplemente permanecemos en NoMoney
        return self


class NotDeliverable(State):
    """
    ESTADO 5: Entrega no es posible
    
    ¿Cuándo se crea?
    - Cuando Delivery indica que no es posible entregar estando en Paid
    
    ¿Qué hace?
    - Guarda estado "NotDeliverable" en BD
    - Publica comando de devolución de dinero
    - Espera confirmación de devolución
    
    ¿A qué estados puede ir?
    - Returned (si money_returned)
    """

    async def on_event(self, event, saga):
        """
        LÓGICA DE NOTDELIVERABLE: Entrega no posible, devolver dinero
        
        En este estado, necesitamos devolver el dinero al cliente.
        """
        
        # CASO 1: Entrega no posible → Iniciar devolución
        if event.get('type') == 'notdeliverable':
            # ✓ Se ejecuta cuando se entra en este estado
            
            # Llamar a saga para publicar comando de devolución
            await saga.publish_return_money_command()
            # → Publica en exchange 'command' con routing_key 'return_money'
            
            # Llamar a saga para escuchar confirmación
            await saga.listen_money_returned()
            # → Se suscribe al exchange 'saga' en cola 'money_returned'
            # → Cuando Payment confirma, el broker llama saga.on_event() automáticamente
            
            return self
        
        # CASO 2: Dinero fue DEVUELTO
        elif event.get('type') == 'money_returned':
            # ✓ Cambiar a estado Returned
            print(f"✓ Dinero devuelto para orden {saga.order_id}")
            #return Returned()
            print(f"✗ Orden {saga.order_id} no entregabe. Dinero devuelto")
            # Publicar evento final al broker
            await saga.publish_event(
                routing_key="payment.failed",
                body=json.dumps({
                    "order_id": saga.order_id,
                    "status": "Not Deliverable",
                    "message": "Order not deliverable, money returned to customer"
                })
            )

            print(f"📤 Evento 'payment.failed' publicado con éxito en el exchange broker.")
            return self
            # → Crea nueva instancia Returned()
            # → Se ejecuta Returned.__init__()
            # → Retorna a OrderSaga.on_event()
            # → OrderSaga detecta cambio: self.state = Returned()
            # → Llama _persist_state() para guardar "Returned" en BD

        return self  # Permanecer en NotDeliverable


class Returned(State):
    """
    ESTADO 6: Dinero devuelto - Orden cancelada
    
    ¿Cuándo se crea?
    - Cuando Payment confirma que devolvió el dinero estando en NotDeliverable
    
    ¿Qué hace?
    - Guarda estado "Returned" en BD
    - FIN DEL FLUJO
    """

    def on_event(self, event, saga):
        """
        LÓGICA DE RETURNED: Dinero devuelto, fin del flujo
        
        Este es el estado final. La orden ha sido cancelada y el dinero devuelto.
        """
        
        # En este estado, la saga ha completado su ciclo
        # Simplemente permanecemos en Returned
        return self
