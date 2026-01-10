# -*- coding: utf-8 -*-
"""Estados del SAGA de cancelación (Order orquestador).

Flujo (según informe):
    1) CANCELING: Order ordena a Warehouse cancelar fabricación.
    2) REFUNDING: cuando Warehouse confirma cancelación, Order ordena refund a Payment.
    3) Final:
        - CANCELED si refund OK
        - CANCEL_PENDING_REFUND si refund falla (no reanudamos fabricación):contentReference[oaicite:2]{index=2}
"""
from sql import models
from services import order_service
from saga.broker_saga.saga_broker_order_cancel import (
    publish_cancel_fabrication_command,
    publish_refund_command,
)


class Canceling:
    """Estado intermedio: evita carreras y permite reintentos."""

    async def on_enter(self, saga):
        """Al entrar, persistimos status y ordenamos cancelar fabricación."""
        await order_service.update_order_fabrication_status(
            order_id=saga.order.id,
            status=models.Order.MFG_CANCELING,
        )
        await order_service.update_cancel_saga(
            saga_id=saga.saga_id,
            state="Canceling",
        )

        await publish_cancel_fabrication_command(
            order_id=saga.order.id,
            saga_id=saga.saga_id,
        )

    async def on_event(self, event, saga):
        """Transiciones desde Canceling."""
        if event.get("type") == "fabrication_canceled":
            return Refunding()
        return self


class Refunding:
    """Estado: solicitando reembolso a Payment."""

    async def on_enter(self, saga):
        """Al entrar, pedimos refund (idempotente por saga_id)."""
        await order_service.update_cancel_saga(
            saga_id=saga.saga_id,
            state="Refunding",
        )

        await publish_refund_command(
            order_id=saga.order.id,
            user_id=saga.order.user_id,
            saga_id=saga.saga_id,
        )

    async def on_event(self, event, saga):
        """Transiciones desde Refunding."""
        if event.get("type") == "refunded":
            return Canceled()
        if event.get("type") == "refund_failed":
            saga.last_error = event.get("reason")
            return CancelPendingRefund()
        return self


class Canceled:
    """Estado final: cancelado y reembolsado."""

    async def on_enter(self, saga):
        """Marcamos el pedido como cancelado (final)."""
        await order_service.update_order_fabrication_status(
            order_id=saga.order.id,
            status=models.Order.MFG_CANCELED,
        )
        await order_service.update_cancel_saga(
            saga_id=saga.saga_id,
            state="Canceled",
        )

    async def on_event(self, event, saga):
        """Final: ignoramos eventos duplicados."""
        return self


class CancelPendingRefund:
    """Estado final coherente: cancelado pero refund pendiente/ha fallado."""

    async def on_enter(self, saga):
        """Persistimos el estado final y el error si lo hay."""
        await order_service.update_order_fabrication_status(
            order_id=saga.order.id,
            status=models.Order.MFG_CANCEL_PENDING_REFUND,
        )
        await order_service.update_cancel_saga(
            saga_id=saga.saga_id,
            state="CancelPendingRefund",
            error=getattr(saga, "last_error", None),
        )

    async def on_event(self, event, saga):
        """Final: ignoramos eventos duplicados."""
        return self
