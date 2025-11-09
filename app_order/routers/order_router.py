# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
#from dependencies import get_db
#from dependencies import get_current_user
from saga.state_machine import order_saga  # importa tu orquestador
from microservice_chassis_grupo2.core.dependencies import get_current_user, get_db
from microservice_chassis_grupo2.core.router_utils import raise_and_log_error
from sql import crud, schemas, models
from broker import order_broker_service
from services import order_service

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/order"
)


@router.get(
    "/health",
    summary="Health check endpoint",
    response_model=schemas.Message,
)
async def health_check():
    """Endpoint to check if everything started correctly."""
    logger.debug("GET '/' endpoint called.")
    return {
        "detail": "OK"
    }

@router.post(
    "",
    response_model=schemas.Order,
    summary="Create single order",
    status_code=status.HTTP_201_CREATED,
    tags=["Order"]
)

@router.post(
    "",
    response_model=schemas.Order,
    summary="Create single order",
    status_code=status.HTTP_201_CREATED,
    tags=["Order"]
)
async def create_order(
    order_schema: schemas.OrderPost,
    db: AsyncSession = Depends(get_db),
    user: int = Depends(get_current_user)
):
    """Create a single order with its pieces and notify the machine service."""
    logger.info("Request received to create order with %d pieces.", order_schema.number_of_pieces)

    try:
        db_order = await crud.create_order_from_schema(db, order_schema, user)

        # Añadir piezas
        for _ in range(order_schema.number_of_pieces):
            db_order = await crud.add_piece_to_order(db, db_order)

        logger.info("Order %s created successfully with %d pieces.", db_order.id, len(db_order.pieces))

        # 🔹 1️⃣ Crear una nueva saga para esta orden
        saga = order_saga.OrderSaga(order_id=db_order.id)

        # 🔹 2️⃣ Enviar el evento inicial a la saga
        event = {
            "type": "order_created",
            "order_data": {
                "order_id": db_order.id,
                "user_id": user,
                "number_of_pieces": db_order.number_of_pieces,
                "address": db_order.address
            }
        }

        # 🔹 3️⃣ Procesar el evento
        await saga.on_event(event)

        return db_order

    except Exception as exc:
        raise_and_log_error(logger, status.HTTP_409_CONFLICT, f"Error creating order: {exc}")



@router.get(
    "",
    response_model=List[schemas.Order],
    summary="Retrieve order list",
    tags=["Order", "List"]  # Optional so it appears grouped in documentation
)
async def get_order_list(
    db: AsyncSession = Depends(get_db),
    user: int = Depends(get_current_user)
):
    """Retrieve order list"""
    logger.debug("GET '/order' endpoint called.")
    order_list = await crud.get_order_list(db)
    return order_list

@router.get(
    "/{order_id}",
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
        user: int = Depends(get_current_user)
):
    """Retrieve single order by id"""
    logger.debug("GET '/order/%i' endpoint called.", order_id)
    order = await crud.get_order(db, order_id)
    if not order:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    return order

@router.put(
    "/status/{order_id}"
)
async def update_order_status(
    order_id: int,
    status: str,
    user: int = Depends(get_current_user)
):
    # Update order status first
    result = await order_service.update_order_status(order_id=order_id, status=status)
    print(status)
    # If status is FINISHED, trigger delivery
    if status == models.Order.STATUS_PAID:
        try:
            logger.info(order_id)
            await order_broker_service.publish_order_created(order_id)
        except Exception as net_exc:
            logger.info(net_exc)
        logger.info("Order %s finished successfully.", order_id)

    return result


@router.delete(
    "/{order_id}",
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
        user: int = Depends(get_current_user)
):
    """Remove order"""
    logger.debug("DELETE '/order/%i' endpoint called.", order_id)
    order = await crud.get_order(db, order_id)
    if not order:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    return await crud.delete_order(db, order_id)