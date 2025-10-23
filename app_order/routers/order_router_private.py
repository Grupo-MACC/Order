# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging
import httpx
import uuid
from typing import List
from fastapi import APIRouter, Depends, status, Body, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db, get_current_user
from sql import crud, schemas, models
from broker import order_broker_service
from .router_utils import raise_and_log_error

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/private",
    tags=["Order", "Private"]
)

@router.get(
        "/piece_status/{status}",
        response_model=List[schemas.Piece]
)
async def get_piece_list_by_status(
    status: str,
    db: AsyncSession = Depends(get_db)
):
    return await crud.get_piece_list_by_status(db=db, status=status)

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