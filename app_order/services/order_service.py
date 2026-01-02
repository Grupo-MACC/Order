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
        2) Si manufacturing avanzó, manda.
        3) Si no, usamos creation_status.
    """
    if order.delivery_status != models.Order.DELIVERY_NOT_STARTED:
        return f"Delivery:{order.delivery_status}"
    if order.manufacturing_status != models.Order.MFG_NOT_STARTED:
        return f"Manufacturing:{order.manufacturing_status}"
    return f"Creation:{order.creation_status}"


async def update_order_creation_status(order_id: int, status: str) -> Optional[models.Order]:
    """Actualiza creation_status."""
    async for db in get_db():
        return await crud.update_order_creation_status(db=db, order_id=order_id, status=status)


async def update_order_manufacturing_status(order_id: int, status: str) -> Optional[models.Order]:
    """Actualiza manufacturing_status."""
    async for db in get_db():
        return await crud.update_order_manufacturing_status(db=db, order_id=order_id, status=status)


async def update_order_delivery_status(order_id: int, status: str) -> Optional[models.Order]:
    """Actualiza delivery_status."""
    async for db in get_db():
        return await crud.update_order_delivery_status(db=db, order_id=order_id, status=status)


async def get_order_by_id(order_id: int) -> Optional[models.Order]:
    """Obtiene una order por id."""
    async for db in get_db():
        return await crud.get_order(db=db, order_id=order_id)
