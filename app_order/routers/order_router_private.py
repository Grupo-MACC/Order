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