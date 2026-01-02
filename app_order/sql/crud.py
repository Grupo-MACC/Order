# -*- coding: utf-8 -*-
"""Funciones CRUD (DB) del microservicio order.

Cambios clave:
    - Eliminamos todas las operaciones sobre `Piece`.
    - La Order ahora almacena cantidades de A/B y total.
    - Añadimos updates de estados por fase (creation/mfg/delivery).
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models

logger = logging.getLogger(__name__)


async def create_order_from_schema(db: AsyncSession, order, current_user):
    """Persist a new order into the database.

    Nota:
        - Calculamos number_of_pieces = pieces_a + pieces_b.
    """
    total = int(order.pieces_a) + int(order.pieces_b)

    db_order = models.Order(
        client_id=current_user,
        description=order.description,
        address=order.address,
        pieces_a=int(order.pieces_a),
        pieces_b=int(order.pieces_b),
        number_of_pieces=total,
        creation_status=models.Order.CREATION_PENDING,
        manufacturing_status=models.Order.MFG_NOT_STARTED,
        delivery_status=models.Order.DELIVERY_NOT_STARTED,
        status=models.Order.CREATION_PENDING,  # legacy sync opcional
    )

    db.add(db_order)
    await db.commit()
    await db.refresh(db_order)
    return db_order


async def get_order_list(db: AsyncSession):
    """Load all orders."""
    result = await db.execute(select(models.Order))
    return result.unique().scalars().all()


async def get_order(db: AsyncSession, order_id: int):
    """Load single order."""
    result = await db.execute(select(models.Order).where(models.Order.id == order_id))
    return result.scalar_one_or_none()


async def delete_order(db: AsyncSession, order_id: int):
    """Delete order."""
    element = await db.get(models.Order, order_id)
    if element is not None:
        await db.delete(element)
        await db.commit()
    return element


async def update_order_creation_status(db: AsyncSession, order_id: int, status: str):
    """Update creation_status (saga creación)."""
    db_order = await db.get(models.Order, order_id)
    if db_order is None:
        return None
    db_order.creation_status = status
    db_order.status = status  # legacy sync opcional
    await db.commit()
    await db.refresh(db_order)
    return db_order


async def update_order_manufacturing_status(db: AsyncSession, order_id: int, status: str):
    """Update manufacturing_status (warehouse)."""
    db_order = await db.get(models.Order, order_id)
    if db_order is None:
        return None
    db_order.manufacturing_status = status
    db_order.status = status  # legacy sync opcional
    await db.commit()
    await db.refresh(db_order)
    return db_order


async def update_order_delivery_status(db: AsyncSession, order_id: int, status: str):
    """Update delivery_status (delivery)."""
    db_order = await db.get(models.Order, order_id)
    if db_order is None:
        return None
    db_order.delivery_status = status
    db_order.status = status  # legacy sync opcional
    await db.commit()
    await db.refresh(db_order)
    return db_order
