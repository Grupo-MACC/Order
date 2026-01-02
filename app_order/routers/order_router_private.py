# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging
from typing import List
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
# from microservice_chassis_grupo2.core.dependencies import get_db
from sql import crud, schemas
from microservice_chassis_grupo2.core.router_utils import raise_and_log_error
from dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/private",
    tags=["Order", "Private"]
)

@router.get("/piece_status/{status}")
async def deprecated_piece_list_by_status(status: str):
    """
    Endpoint legacy: Order ya no gestiona piezas individuales.
    """
    raise HTTPException(
        status_code=410,
        detail="Deprecated: Order ya no expone piezas individuales. Consulta Warehouse.",
    )

@router.get("/piece/{piece_id}")
async def deprecated_get_piece(piece_id: int):
    """
    Endpoint legacy: Order ya no gestiona piezas individuales.
    """
    raise HTTPException(
        status_code=410,
        detail="Deprecated: Order ya no expone piezas individuales. Consulta Warehouse.",
    )

@router.get(
    "/order/{order_id}",
    summary="Retrieve single order by id",
    responses={
        status.HTTP_200_OK: {
            "model": schemas.Order,
            "description": "Requested Order."
        },
        status.HTTP_404_NOT_FOUND: {
            "model": schemas.Message, "description": "Order not found"
        }
    },
    tags=['Order']
)
async def get_single_order(
        order_id: int,
        db: AsyncSession = Depends(get_db),
):
    """Retrieve single order by id"""
    logger.debug("GET '/order/%i' endpoint called.", order_id)
    order = await crud.get_order(db, order_id)
    if not order:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    return order