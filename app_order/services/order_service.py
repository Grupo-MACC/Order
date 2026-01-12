# -*- coding: utf-8 -*-
"""Capa de servicio del microservicio order.

Cambios:
    - Eliminamos piezas individuales.
    - Añadimos updates de estado por fase.
    - Añadimos compute_overall_status para la UI.
"""

from __future__ import annotations
from typing import Optional
from microservice_chassis_grupo2.core.dependencies import get_db
from sql import crud, models


def compute_overall_status(order: models.Order) -> str:
    """Deriva un estado 'global' legible para el cliente.

    Regla simple:
        1) Si delivery avanzó, manda.
        2) Si fabrication avanzó, manda.
        3) Si no, usamos creation_status.
    """
    if order.delivery_status != models.Order.DELIVERY_NOT_STARTED:
        return f"Delivery:{order.delivery_status}"
    if order.fabrication_status != models.Order.MFG_NOT_STARTED:
        return f"Manufacturing:{order.fabrication_status}"
    return f"Creation:{order.creation_status}"


async def update_order_creation_status(order_id: int, status: str) -> Optional[models.Order]:
    """Actualiza creation_status."""
    async for db in get_db():
        return await crud.update_order_creation_status(db=db, order_id=order_id, status=status)


async def update_order_fabrication_status(order_id: int, status: str) -> Optional[models.Order]:
    """Actualiza fabrication_status."""
    async for db in get_db():
        return await crud.update_order_fabrication_status(db=db, order_id=order_id, status=status)


async def update_order_delivery_status(order_id: int, status: str) -> Optional[models.Order]:
    """Actualiza delivery_status."""
    async for db in get_db():
        return await crud.update_order_delivery_status(db=db, order_id=order_id, status=status)


async def get_order_by_id(order_id: int) -> Optional[models.Order]:
    """Obtiene una order por id."""
    async for db in get_db():
        return await crud.get_order(db=db, order_id=order_id)

async def create_cancel_saga(saga_id: str, order_id: int, state: str) -> Optional[models.CancelSaga]:
    """Crea una saga de cancelación en BD."""
    async for db in get_db():
        return await crud.create_cancel_saga(db=db, saga_id=saga_id, order_id=order_id, state=state)


async def update_cancel_saga(saga_id: str, state: str, error: str | None = None) -> Optional[models.CancelSaga]:
    """Actualiza el estado interno de la saga de cancelación."""
    async for db in get_db():
        return await crud.update_cancel_saga(db=db, saga_id=saga_id, state=state, error=error)
