# -*- coding: utf-8 -*-
"""Manager de sagas de cancelación.

Nota:
    - Se indexa por saga_id (no por order_id), porque RabbitMQ puede reentregar
      y queremos correlación exacta con el flujo de cancelación.
"""
import asyncio
from saga.state_machine.order_cancel_saga import CancelSaga


class CancelSagaManager:
    """Gestiona sagas activas de cancelación (en memoria)."""

    def __init__(self):
        self.active_sagas: dict[str, CancelSaga] = {}

    def start_saga(self, order, saga_id: str):
        """Crea y arranca una saga."""
        async def on_finish(done_saga_id: str):
            self.remove_saga(done_saga_id)

        saga = CancelSaga(order=order, saga_id=saga_id, on_finish=on_finish)
        self.active_sagas[str(saga_id)] = saga

        async def run():
            await saga.start()

        asyncio.create_task(run())

    def get_saga(self, saga_id: str) -> CancelSaga | None:
        """Obtiene saga activa por saga_id."""
        return self.active_sagas.get(str(saga_id))

    def remove_saga(self, saga_id: str):
        """Elimina saga activa."""
        self.active_sagas.pop(str(saga_id), None)


cancel_saga_manager = CancelSagaManager()
