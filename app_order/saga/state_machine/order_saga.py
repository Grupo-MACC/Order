from saga.state_machine.my_states import Pending
import logging
from services.order_service import update_order_status

FINAL_STATES = {"Confirmed", "NoMoney", "Returned"}

logger = logging.getLogger(__name__)

class OrderSaga():

    def __init__(self, order, on_finish=None):
        self.order = order
        self.state = Pending()
        self.on_finish = on_finish
    
    async def start(self):
        #await self._persist_state()
        if hasattr(self.state, "on_enter"):
            await self.state.on_enter(self)
        
    async def _persist_state(self):
        try:
            await update_order_status(self.order.id, str(self.state.__class__.__name__))
            print(f"💾 Estado de saga persistido en BD: {self.state.__class__.__name__}")
        except Exception as e:
            print(f"❌ Error persistiendo estado de saga en BD: {e}")
    async def on_event_saga(self, event):
        try:
            print(f"📨 Evento recibido por Saga: {event}")
            new_state = await self.state.on_event(event, self)

            if new_state.__class__ != self.state.__class__:
                old, new = self.state.__class__.__name__, new_state.__class__.__name__
                print(f"  → Cambio de estado {old} → {new}")

                self.state = new_state
                await self._persist_state()

                # Ejecutar lógica on_enter del nuevo estado (si existe)
                if hasattr(new_state, "on_enter"):
                    await new_state.on_enter(self)

                # Si estado es final → eliminar saga
                if new in FINAL_STATES:
                #    from saga.state_machine.saga_manager import saga_manager
                #    saga_manager.remove_saga(self.order.id)
                    print(f"✅ Saga de orden {self.order.id} ha alcanzado estado final: {new}")
                    if self.on_finish:
                        await self.on_finish(self.order.id)

            else:
                print(f"⏸ Estado sin cambios: {self.state.__class__.__name__}")

        except Exception as e:
            print(f"❌ Error procesando evento en saga de orden {self.order.id}: {e}")