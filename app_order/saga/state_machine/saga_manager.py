import asyncio
from saga.state_machine.order_saga import OrderSaga

class SagaManager:
    def __init__(self):
        self.active_sagas = {}
    
    def start_saga(self, order):
        async def on_finish(order_id):
            self.remove_saga(order_id)
        saga = OrderSaga(order, on_finish=on_finish)
        self.active_sagas[order.id] = saga
        
        async def run_saga():
            try:
                await saga.start()
            except Exception as e:
                print(f"⚠️ Error en la ejecución de la saga para el pedido {order.id}: {e}")
                import traceback
                traceback.print_exc()
                
        asyncio.create_task(run_saga())

    def get_saga(self, order_id)-> OrderSaga:
        return self.active_sagas.get(order_id)
    
    def remove_saga(self, order_id):
        if order_id in self.active_sagas:
            del self.active_sagas[order_id]
            
saga_manager = SagaManager()