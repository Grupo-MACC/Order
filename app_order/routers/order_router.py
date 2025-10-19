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
from .router_utils import raise_and_log_error, MACHINE_SERVICE_URL, DELIVERY_SERVICE_URL, PAYMENT_SERVICE_URL
from broker import order_broker_service
ONE_PIECE_PRICE = 120
CURRENCY = "EUR"

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    summary="Health check endpoint",
    response_model=schemas.Message,
)
async def health_check():
    """Endpoint to check if everything started correctly."""
    logger.debug("GET '/' endpoint called.")
    return {
        "detail": "OK"
    }


# Orders ###########################################################################################
@router.post(
    "/order",
    response_model=schemas.Order,
    summary="Create single order",
    status_code=status.HTTP_201_CREATED,
    tags=["Order"]
)
async def create_order(
    order_schema: schemas.OrderPost,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """Create a single order with its pieces and notify the machine service."""
    logger.info("Request received to create order with %d pieces.", order_schema.number_of_pieces)

    try:
        # Crear el pedido en la BD
        db_order = await crud.create_order_from_schema(db, order_schema, current_user)
        logger.info(db_order)
        # Añadir piezas al pedido
        for _ in range(order_schema.number_of_pieces):
            db_order = await crud.add_piece_to_order(db, db_order)
        # payment_payload = {
        #     "order_id": db_order.id,
        #     "amount_minor": int(ONE_PIECE_PRICE * 100 * db_order.number_of_pieces),  # si total_amount está en euros
        #     "currency": CURRENCY
        # }
        '''try:
            async with httpx.AsyncClient() as client:
                
                response = await client.post(
                    f"{PAYMENT_SERVICE_URL}/payment",
                    json=payment_payload
                )
                response.raise_for_status()
        c
            print(net_exc)'''
        try:
            logger.info(db_order)
            logger.info(db_order.id)
            await order_broker_service.publish_order_created(db_order.id)
        except Exception as net_exc:
            logger.info(net_exc)
        logger.info("Order %s created successfully with %d pieces.", db_order.id, len(db_order.pieces))
        print(db_order)
        return db_order
        
    except ValueError as val_exc:
        raise_and_log_error(logger, status.HTTP_400_BAD_REQUEST, f"Invalid data: {val_exc}")
    except Exception as exc:  # TODO: Afinar excepciones
        raise_and_log_error(logger, status.HTTP_409_CONFLICT, f"Error creating order: {exc}")



@router.get(
    "/order",
    response_model=List[schemas.Order],
    summary="Retrieve order list",
    tags=["Order", "List"]  # Optional so it appears grouped in documentation
)
async def get_order_list(
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """Retrieve order list"""
    logger.debug("GET '/order' endpoint called.")
    order_list = await crud.get_order_list(db)
    return order_list

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
        current_user: str = Depends(get_current_user)
):
    """Retrieve single order by id"""
    logger.debug("GET '/order/%i' endpoint called.", order_id)
    order = await crud.get_order(db, order_id)
    if not order:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    return order

@router.put(
    "/update_order_status/{order_id}"
)
async def update_order_status(
    order_id: int,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    # Update order status first
    result = await crud.update_order_status(db=db, order_id=order_id, status=status)
    print(status)
    # If status is FINISHED, trigger delivery
    if status == models.Order.STATUS_FINISHED:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{DELIVERY_SERVICE_URL}/deliver/{order_id}"
                )
                response.raise_for_status()
                logger.info(f"Delivery triggered for order {order_id}")
        except Exception as e:
            logger.error(f"Failed to trigger delivery for order {order_id}: {e}")
            # You might want to handle this error differently
    
    return result


@router.delete(
    "/order/{order_id}",
    summary="Delete order",
    responses={
        status.HTTP_200_OK: {
            "model": schemas.Order,
            "description": "Order successfully deleted."
        },
        status.HTTP_404_NOT_FOUND: {
            "model": schemas.Message, "description": "Order not found"
        }
    },
    tags=["Order"]
)
async def remove_order_by_id(
        order_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: str = Depends(get_current_user)
):
    """Remove order"""
    logger.debug("DELETE '/order/%i' endpoint called.", order_id)
    order = await crud.get_order(db, order_id)
    if not order:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    # Notificar al servicio de máquina
    try:
        piece_ids = [p.id for p in order.pieces]
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{MACHINE_SERVICE_URL}/remove_pieces_from_queue",
                params=[("piece_ids", pid) for pid in piece_ids]
            )
            response.raise_for_status()
    except Exception as net_exc:
        raise_and_log_error(
            logger,
            status.HTTP_502_BAD_GATEWAY,
            f"Failed to contact machine service: {net_exc}"
        )
    return await crud.delete_order(db, order_id)

@router.patch(
        "/order/payment_made/{order_id}"
)
async def payment_made_process(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    order_db = await crud.update_order_status(db=db, order_id=order_id, status=models.Order.STATUS_PAYED)
    if not order_db:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    pieces = [str(piece.id) for piece in order_db.pieces]
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{MACHINE_SERVICE_URL}/machine/add_pieces_to_queue",
                json= pieces
            )
            response.raise_for_status()

    except Exception as net_exc:
        print("error")
        raise_and_log_error(
            logger,
            status.HTTP_502_BAD_GATEWAY,
            f"Failed to contact machine service: {net_exc}"
        )
    return {"message": f"Estado de la orden {order_id} actualizado a {order_db.status}"}


# Pieces ###########################################################################################
@router.get(
    "/piece",
    response_model=List[schemas.Piece],
    summary="retrieve piece list",
    tags=["Piece", "List"]
)
async def get_piece_list(
        db: AsyncSession = Depends(get_db),
        current_user: str = Depends(get_current_user)
):
    """Retrieve the list of pieces."""
    logger.debug("GET '/piece' endpoint called.")
    return await crud.get_piece_list(db)

@router.get(
        "/piece_status/{status}",
        response_model=List[schemas.Piece]
)
async def get_piece_list_by_status(
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    return await crud.get_piece_list_by_status(db=db, status=status)

@router.get(
    "/piece/{piece_id}",
    summary="Retrieve single piece by id",
    response_model=schemas.Piece,
    tags=['Piece']
)
async def get_single_piece(
        piece_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: str = Depends(get_current_user)
):
    """Retrieve single piece by id"""
    print("GET '/piece/%i' endpoint called.", piece_id)
    return await crud.get_piece(db, piece_id)

@router.put(
    "/update_piece_status/{piece_id}",
    response_model=schemas.Piece
)
async def update_piece_status(
    piece_id: str,
    status: str = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    print(piece_id)
    return await crud.update_piece_status(db=db, piece_id=piece_id, status=status)

@router.put(
    "/update_piece_manufacturing_date_to_now/{piece_id}",
    response_model=schemas.Piece
)
async def update_piece_manufacturing_date_to_now(
    piece_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    return await crud.update_piece_manufacturing_date_to_now(db=db, piece_id=piece_id)