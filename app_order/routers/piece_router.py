# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging
from typing import List
from fastapi import APIRouter, Depends, Body, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
#from dependencies import get_db
#from dependencies import get_current_user
from microservice_chassis_grupo2.core.dependencies import get_current_user, get_db, check_public_key
from microservice_chassis_grupo2.core.router_utils import raise_and_log_error
from sql import crud, schemas

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/piece"
)

@router.get(
    "/health",
    summary="Health check endpoint",
    response_model=schemas.Message,
)
async def health_check():
    """Endpoint to check if everything started correctly."""
    logger.debug("GET '/health' endpoint called.")
    if check_public_key():
        return {"detail": "OK"}
    else:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not available")

@router.get(
    "",
    response_model=List[schemas.Piece],
    summary="retrieve piece list",
    tags=["Piece", "List"]
)
async def get_piece_list(
        db: AsyncSession = Depends(get_db),
        user: int = Depends(get_current_user)
):
    """Retrieve the list of pieces."""
    logger.debug("GET '/piece' endpoint called.")
    return await crud.get_piece_list(db)

@router.get(
        "/status/{status}",
        response_model=List[schemas.Piece]
)
async def get_piece_list_by_status(
    status: str,
    db: AsyncSession = Depends(get_db),
    user: int = Depends(get_current_user)
):
    return await crud.get_piece_list_by_status(db=db, status=status)

@router.get(
    "/{piece_id}",
    summary="Retrieve single piece by id",
    response_model=schemas.Piece,
    tags=['Piece']
)
async def get_single_piece(
        piece_id: int,
        db: AsyncSession = Depends(get_db),
        user: int = Depends(get_current_user)
):
    """Retrieve single piece by id"""
    print("GET '/piece/%i' endpoint called.", piece_id)
    return await crud.get_piece(db, piece_id)

@router.put(
    "/status/{piece_id}",
    response_model=schemas.Piece
)
async def update_piece_status(
    piece_id: str,
    status: str = Body(...),
    db: AsyncSession = Depends(get_db),
    user: int = Depends(get_current_user)
):
    print(piece_id)
    return await crud.update_piece_status(db=db, piece_id=piece_id, status=status)