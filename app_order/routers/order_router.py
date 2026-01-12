# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging, uuid, os
from typing import List
import asyncio
from fastapi import APIRouter, Depends, status, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
#from dependencies import get_db
#from dependencies import get_current_user
from microservice_chassis_grupo2.core.dependencies import get_current_user, check_public_key
from microservice_chassis_grupo2.core.router_utils import raise_and_log_error
from dependencies import get_db
from sql import crud, schemas, models
from broker import order_broker_service
from services import order_service

from saga.state_machine.order_confirm_saga_manager import saga_manager
from saga.state_machine.order_cancel_saga_manager import cancel_saga_manager

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
    logger.debug("GET '/health' endpoint called.")
    if check_public_key():
        return {"detail": "OK"}
    else:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not available")

#region POST /order
@router.post(
    "",
    summary="Create single order",
    status_code=status.HTTP_201_CREATED,
    tags=["Order"],
)
async def create_order(
    order_schema: schemas.OrderPost,
    db: AsyncSession = Depends(get_db),
    user: int = Depends(get_current_user),
):
    """
    Crea una order (cantidades A/B) y arranca el SAGA de confirmación.

    Importante:
        - Aquí NO se dispara fabricación.
        - La fabricación se dispara cuando el SAGA alcanza Confirmed.
    """
    if int(order_schema.pieces_a) == 0 and int(order_schema.pieces_b) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debes solicitar al menos 1 pieza (A o B).",
        )

    try:
        db_order = await crud.create_order_from_schema(db, order_schema, user)

        # DTO para la saga (Pydantic desde ORM)
        order_dto = schemas.Order.model_validate(db_order)

        saga_manager.start_saga(order_dto)

        return {
            "order_id": db_order.id,
            "creation_status": db_order.creation_status,
            "message": "Order received and being processed",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error creating order: {exc}")

#region GET /order
@router.get(
    "",
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

#region GET /order/{order_id}
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
        return HTTPException(status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    return order


#region GET /order/status/id
@router.get(
    "/{order_id}/status",
    summary="Retrieve order status (creation/fabrication/delivery)",
    response_model=schemas.OrderStatusResponse,
    tags=["Order"],
)
async def get_order_status(
    order_id: int,
    user: int = Depends(get_current_user),
):
    """
    Devuelve el estado por fases.
    """
    order = await order_service.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    overall = order_service.compute_overall_status(order)

    return schemas.OrderStatusResponse(
        order_id=order.id,
        creation_status=order.creation_status,
        fabrication_status=order.fabrication_status,
        delivery_status=order.delivery_status,
        overall_status=overall,
    )

#region PUT /order/status/id
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

#region POST /order/id/cancel
@router.post(
    "/{order_id}/cancel",
    summary="Cancel order while fabrication (starts cancel SAGA)",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Order"],
)
async def cancel_order_in_fabrication(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user: int = Depends(get_current_user),
):
    """Inicia el SAGA de cancelación en fabricación.

    Validación (según informe):
        - Debe estar pagado y en fabricación:contentReference[oaicite:3]{index=3}
        - Si no, se rechaza sin iniciar la saga

    Efecto:
        - Pasa fabrication_status a Canceling
        - Publica cmd.cancel_fabrication a Warehouse
        - Continúa por eventos (evt.fabrication_canceled → cmd.refund → refund.result)
    """
    db_order = await crud.get_order(db, order_id)
    if not db_order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    # Seguridad mínima: solo dueño o el admin puede cancelar
    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "1"))

    is_admin = int(user) == ADMIN_USER_ID
    is_owner = int(db_order.client_id) == int(user)

    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=403,
            detail="You cannot cancel orders from another user",
        )

    # Validación de cancelabilidad:
    # - Pago confirmado por la saga de creación
    # - Fabricación en curso (Requested o InProgress)
    if db_order.creation_status != models.Order.CREATION_CONFIRMED:
        raise HTTPException(
            status_code=409,
            detail=f"Order not cancelable: creation_status={db_order.creation_status}",
        )

    if db_order.fabrication_status not in {models.Order.MFG_REQUESTED, models.Order.MFG_IN_PROGRESS}:
        raise HTTPException(
            status_code=409,
            detail=f"Order not cancelable: fabrication_status={db_order.fabrication_status}",
        )

    # Evitar duplicados (si ya está cancelando o finalizada)
    if db_order.fabrication_status in {models.Order.MFG_CANCELING, models.Order.MFG_CANCELED, models.Order.MFG_CANCEL_PENDING_REFUND}:
        raise HTTPException(status_code=409, detail="Cancel already requested or finished")

    saga_id = str(uuid.uuid4())

    # Persistimos saga + ponemos estado intermedio CANCELING (evita carreras):contentReference[oaicite:4]{index=4}
    await crud.create_cancel_saga(db, saga_id=saga_id, order_id=db_order.id, state="Canceling")
    await crud.update_order_fabrication_status(db, order_id=db_order.id, status=models.Order.MFG_CANCELING)

    # Arrancamos saga en memoria
    order_dto = schemas.Order.model_validate(db_order)
    cancel_saga_manager.start_saga(order=order_dto, saga_id=saga_id)

    return {
        "detail": "Cancel SAGA started",
        "order_id": db_order.id,
        "saga_id": saga_id,
        "fabrication_status": models.Order.MFG_CANCELING,
    }