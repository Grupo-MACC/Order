# -*- coding: utf-8 -*-
"""
Estados (State Pattern) del SAGA de confirmación de pedido.

Este módulo define los estados por los que pasa la confirmación:
    Pending -> Paid -> Confirmed
              |         |
              v         v
            NoMoney   (publica a Warehouse)

Y el camino alternativo si no es entregable:
    Paid -> NotDeliverable -> Returned

Cada estado es una subclase de State e implementa la lógica de transición y los efectos secundarios
(así como los logs asociados). 
"""

import logging
from typing import Dict, Any

from broker.order_broker_service import publish_do_order
from saga.broker_saga import saga_broker_order_confirm
from services import order_service
from sql import models

logger = logging.getLogger(__name__)

# =============================================================================
# Tipos de eventos internos (único punto de control)
# =============================================================================

EVT_ORDER_CREATED = "order_created"

EVT_PAYMENT_ACCEPTED = "payment_accepted"
EVT_PAYMENT_REJECTED = "payment_rejected"

EVT_DELIVERY_POSSIBLE = "delivery_possible"
EVT_DELIVERY_NOT_POSSIBLE = "delivery_not_possible"

EVT_MONEY_RETURNED = "money_returned"

# Alias / compatibilidad (aparecen en el código original aunque no encajen bien)
EVT_PAID_ALIAS = "paid"
EVT_NOTDELIVERABLE_ALIAS = "notdeliverable"


# =============================================================================
# Clase base de Estado
# =============================================================================
#region 1. CLASE BASE
class State:
    """
    Interfaz base para estados del SAGA.

    Reglas:
        - on_enter(saga): se ejecuta al entrar en el estado (side-effects).
        - on_event(event, saga): procesa un evento y devuelve:
            * self (si no hay transición)
            * una instancia de otro State (si transiciona)
    """

    name: str = "State"

    async def on_event(self, event: Dict[str, Any], saga) -> "State":
        """
        Procesa un evento.

        Args:
            event:
                Diccionario con al menos {"type": "..."}.
            saga:
                Instancia de la saga que contiene la order y el estado actual.

        Returns:
            State:
                Nuevo estado o self si no hay transición.
        """
        return self

    async def on_enter(self, saga) -> None:
        """
        Hook de entrada al estado.

        Aquí suelen ocurrir side-effects (publicar comandos, actualizar DB, etc.).
        """
        return None

    def _trace(self, message: str, level: int = logging.INFO, *, also_print: bool = True) -> None:
        """
        Registra una traza con el nivel indicado.

        Args:
            message:
                Texto del log.
            level:
                Nivel de logging (logging.INFO, logging.WARNING, logging.ERROR, etc.).
            also_print:
                Si True, también imprime por consola (útil en desarrollo/local).

        Nota:
            - logger.log(level, ...) permite usar cualquier nivel sin duplicar código.
            - Mantengo print para conservar visibilidad (pero puedes apagarlo fácilmente).
        """
        logger.log(level, message)

        if also_print:
            # Print simple (sin colores ni formatos raros) para entornos docker/local.
            print(message)

    def _debug(self, message: str, *, also_print: bool = True) -> None:
        """Atajo para logs debugging."""
        self._trace(message, logging.DEBUG, also_print=also_print)

    def _info(self, message: str, *, also_print: bool = True) -> None:
        """Atajo para logs informativos."""
        self._trace(message, logging.INFO, also_print=also_print)

    def _warn(self, message: str, *, also_print: bool = True) -> None:
        """Atajo para warnings."""
        self._trace(message, logging.WARNING, also_print=also_print)

    def _error(self, message: str, *, also_print: bool = True) -> None:
        """Atajo para errores."""
        self._trace(message, logging.ERROR, also_print=also_print)


# =============================================================================
# Estados concretos
# =============================================================================
#region 2. ORDER PENDING
class Pending(State):
    """
    Estado inicial de confirmación:
        - Al entrar: publica comando de pago.
        - Con evento payment_accepted -> Paid
        - Con evento payment_rejected -> NoMoney
    """

    name = "Pending"

    async def on_event(self, event: Dict[str, Any], saga) -> State:
        evt = (event.get("type") or "").strip()

        if evt == EVT_ORDER_CREATED:
            # En el código original, este evento no cambiaba nada.
            # Mantenemos el comportamiento (no transición).
            return self

        if evt == EVT_PAYMENT_ACCEPTED:
            self._debug(f"✓ Pago aceptado para orden {saga.order.id}")
            return Paid()

        if evt == EVT_PAYMENT_REJECTED:
            self._warn(f"✗ Pago rechazado para orden {saga.order.id}")
            return NoMoney()

        return self

    async def on_enter(self, saga) -> None:
        self._info(f"➡️ Orden {saga.order.id} en estado Pending. Publicando comando de pago...")
        await saga_broker_order_confirm.publish_payment_command(saga.order)

#region 3. ORDER PAID
class Paid(State):
    """
    Estado tras pago aceptado:
        - Al entrar: publica comando de verificación de entrega.
        - Con evento delivery_possible -> Confirmed
        - Con evento delivery_not_possible -> NotDeliverable
    """

    name = "Paid"

    async def on_event(self, event: Dict[str, Any], saga) -> State:
        evt = (event.get("type") or "").strip()

        # Compatibilidad: existe en tu código original aunque no tenga efecto real.
        # Mantengo "no-op" explícito para que no sorprenda a nadie.
        if evt == EVT_PAID_ALIAS:
            return self

        if evt == EVT_DELIVERY_POSSIBLE:
            self._debug(f"✓ Entrega posible para orden {saga.order.id}")
            return Confirmed()

        if evt == EVT_DELIVERY_NOT_POSSIBLE:
            self._warn(f"✗ Entrega no posible para orden {saga.order.id}")
            return NotDeliverable()

        return self

    async def on_enter(self, saga) -> None:
        self._info(
            f"➡️ Orden {saga.order.id} en estado Paid. Publicando comando de verificación de entrega..."
        )
        await saga_broker_order_confirm.publish_delivery_check_command(saga.order)

#region 4. ORDER CONFIRMED
class Confirmed(State):
    """
    Estado final “feliz”:
        - Pago OK + Entrega OK.
        - Al entrar:
            * marca fabricación como solicitada (MFG_REQUESTED)
            * publica el comando mínimo a Warehouse (do_order)
    """

    name = "Confirmed"

    async def on_event(self, event: Dict[str, Any], saga) -> State:
        evt = (event.get("type") or "").strip()

        # En tu código original existe este evento "confirmed" pero no parece emitirse.
        # Mantengo el comportamiento: no transición.
        if evt == "confirmed":
            self._debug(f"✅ Orden {saga.order.id} confirmada.")
            return self

        return self

    async def on_enter(self, saga) -> None:
        """
        La order está confirmada (pago OK + delivery-check OK).

        A partir de aquí:
            - Order NO habla con Machine.
            - Order publica comando mínimo a Warehouse.
        """
        self._info(
            f"➡️ Orden {saga.order.id} en estado Confirmed. Publicando do.order a Warehouse..."
        )

        # Marca fabricación como solicitada (útil para UI/estado inmediato)
        await order_service.update_order_fabrication_status(
            order_id=saga.order.id,
            status=models.Order.MFG_REQUESTED,
        )

        # Publica comando mínimo (Warehouse fabricará / consumirá stock)
        await publish_do_order(
            order_id=saga.order.id,
            number_of_pieces=saga.order.number_of_pieces,
            pieces_a=saga.order.pieces_a,
            pieces_b=saga.order.pieces_b,
        )

#region 5. NO MONEY
class NoMoney(State):
    """
    Estado terminal si el pago es rechazado.
    """

    name = "NoMoney"

    async def on_event(self, event: Dict[str, Any], saga) -> State:
        return self

    async def on_enter(self, saga) -> None:
        self._warn(f"✗ Orden {saga.order.id} en estado NoMoney. Fin del flujo.")

#region 6. NOT DELIVERABLE
class NotDeliverable(State):
    """
    Estado cuando Delivery indica que NO es entregable:
        - Al entrar: solicita devolución del dinero.
        - Con evento money_returned -> Returned
    """

    name = "NotDeliverable"

    async def on_event(self, event: Dict[str, Any], saga) -> State:
        evt = (event.get("type") or "").strip()

        # Compatibilidad: aparece en tu original como evento "notdeliverable" (no-op)
        if evt == EVT_NOTDELIVERABLE_ALIAS:
            return self

        if evt == EVT_MONEY_RETURNED:
            self._debug(f"✓ Dinero devuelto para orden {saga.order.id}")
            return Returned()

        return self

    async def on_enter(self, saga) -> None:
        self._info(
            f"➡️ Orden {saga.order.id} en estado NotDeliverable. Solicitando devolución de dinero..."
        )
        await saga_broker_order_confirm.publish_return_money_command(saga.order)

#region 7. MONEY RETURNED
class Returned(State):
    """
    Estado terminal tras confirmación de devolución.
    """

    name = "Returned"

    async def on_event(self, event: Dict[str, Any], saga) -> State:
        return self

    async def on_enter(self, saga) -> None:
        self._info(f"➡️ Orden {saga.order.id} en estado Returned. Fin del flujo.")
