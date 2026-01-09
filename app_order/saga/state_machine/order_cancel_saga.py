# -*- coding: utf-8 -*-
"""SAGA de cancelación de pedido en fabricación.

Responsabilidad:
    - Orquestar cancelación en Warehouse.
    - Tras confirmación de cancelación, orquestar refund en Payment.
"""
import logging
from saga.state_machine.order_cancel_states import Canceling

logger = logging.getLogger(__name__)

FINAL_STATES = {"Canceled", "CancelPendingRefund"}


class CancelSaga:
    """Instancia en memoria del SAGA de cancelación."""

    def __init__(self, order, saga_id: str, on_finish=None):
        """
        Args:
            order:
                DTO Pydantic (schemas.Order) con id y user_id.
            saga_id:
                UUID de correlación.
            on_finish:
                Callback async al terminar (para limpiar manager).
        """
        self.order = order
        self.saga_id = str(saga_id)
        self.state = Canceling()
        self.on_finish = on_finish
        self.last_error = None

    async def start(self):
        """Arranca la saga ejecutando on_enter del estado inicial."""
        if hasattr(self.state, "on_enter"):
            await self.state.on_enter(self)

    async def on_event_saga(self, event: dict):
        """Procesa un evento y transiciona de estado si aplica."""
        new_state = await self.state.on_event(event, self)

        if new_state.__class__ != self.state.__class__:
            old_name = self.state.__class__.__name__
            new_name = new_state.__class__.__name__
            logger.info("[CANCEL_SAGA] %s → %s (order=%s saga=%s)", old_name, new_name, self.order.id, self.saga_id)

            self.state = new_state

            if hasattr(new_state, "on_enter"):
                await new_state.on_enter(self)

            if new_name in FINAL_STATES and self.on_finish:
                await self.on_finish(self.saga_id)
