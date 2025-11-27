from broker.order_broker_service import publish_do_pieces
from saga.broker_saga import saga_broker_service
from services import order_service
from sql import models

class Pending():

    async def on_event(self, event, saga):
        if event.get('type') == 'order_created':
            #await saga_broker_service.publish_payment_command(event.get('order_data', {}))
            return self
        elif event.get('type') == 'payment_accepted':
            print(f"✓ Pago aceptado para orden {saga.order.id}")
            return Paid()
        elif event.get('type') == 'payment_rejected':
            print(f"✗ Pago rechazado para orden {saga.order.id}")
            return NoMoney()
        return self

    async def on_enter(self, saga):
        print(f"➡️ Orden {saga.order.id} en estado Pending. Publicando comando de pago...")
        await saga_broker_service.publish_payment_command(saga.order)

class Paid():

    async def on_event(self, event, saga):
        if event.get('type') == 'paid':
            #await saga_broker_service.publish_delivery_check_command(event.get('order_data', {}))            
            return self
        elif event.get('type') == 'delivery_possible':
            print(f"✓ Entrega posible para orden {saga.order.id}")
            return Confirmed()
        elif event.get('type') == 'delivery_not_possible':
            print(f"✗ Entrega no posible para orden {saga.order.id}")
            return NotDeliverable()
        return self

    async def on_enter(self, saga):
        print(f"➡️ Orden {saga.order.id} en estado Paid. Publicando comando de verificación de entrega...")
        await saga_broker_service.publish_delivery_check_command(saga.order)

class Confirmed():

    async def on_event(self, event, saga):
        if event.get("type") == "confirmed":
            print(f"✅ Orden {saga.order.id} confirmada. Publicando evento 'payment.paid'...")
            #await publish_do_pieces(saga.order.id, [str(piece) for piece in saga.order.pieces])
            return self
        return self
    
    async def on_enter(self, saga):
        print(f"➡️ Orden {saga.order.id} en estado Confirmed. Publicando evento 'payment.paid'...")
        await publish_do_pieces(saga.order.id, [str(piece) for piece in saga.order.pieces])

class NoMoney():

    async def on_event(self, event, saga):
        return self
    
    async def on_enter(self, saga):
        print(f"✗ Orden {saga.order.id} en estado NoMoney. Fin del flujo.")
        await order_service.update_order_pieces_status(saga.order.id, models.Piece.STATUS_CANCELLED)

class NotDeliverable():

    async def on_event(self, event, saga):
        if event.get('type') == 'notdeliverable':
            #await saga_broker_service.publish_return_money_command(event.get('order_data', {}))
            return self
        elif event.get('type') == 'money_returned':
            print(f"✓ Dinero devuelto para orden {saga.order.id}")
            return Returned()
        return self

    async def on_enter(self, saga):
        print(f"➡️ Orden {saga.order.id} en estado NotDeliverable. Publicando comando de devolución de dinero...")
        await saga_broker_service.publish_return_money_command(saga.order)
        await order_service.update_order_pieces_status(saga.order.id, models.Piece.STATUS_CANCELLED)

class Returned():
    
    async def on_event(self, event, saga):
        return self

    async def on_enter(self, saga):
        print(f"➡️ Orden {saga.order.id} en estado Returned. Fin del flujo.")
