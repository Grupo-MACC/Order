# -*- coding: utf-8 -*-
"""
Broker RabbitMQ para el SAGA de cancelación (Order).

Responsabilidades:
    - Publicar comandos del SAGA:
        * cmd.cancel_fabrication  -> Warehouse (ordenar cancelación fabricación)
        * cmd.refund              -> Payment   (ordenar devolución tras cancelación)

    - Consumir eventos del SAGA:
        * evt.fabrication_canceled <- Warehouse (confirmación cancelación fabricación)
        * refund.result            <- Payment   (resultado refund)

Notas de diseño:
    - Todas las routing keys y colas se definen como constantes en un único punto.
    - Los comandos se publican en exchange_command.
    - Los eventos del saga se consumen desde exchange_saga.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any

from aio_pika import Message

from microservice_chassis_grupo2.core.rabbitmq_core import (
    get_channel,
    declare_exchange_command,
    declare_exchange_saga,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Constantes RabbitMQ (routing keys / colas / topics)
# =============================================================================

# --- Comandos hacia otros microservicios
RK_CMD_CANCEL_MFG = "cmd.cancel_fabrication"
RK_CMD_REFUND = "cmd.refund"

# --- Eventos recibidos desde otros microservicios
RK_EVT_MFG_CANCELED = "evt.fabrication_canceled"

# --- Eventos recibidos desde payment (refund)
RK_EVT_REFUND_RESULT = "refund.result"
RK_EVT_REFUNDED_ALT = "evt_refunded"
RK_EVT_REFUND_FAILED_ALT = "evt_refund_failed"

RK_EVT_REFUND_EVENTS = (
    RK_EVT_REFUND_RESULT,
    RK_EVT_REFUNDED_ALT,
    RK_EVT_REFUND_FAILED_ALT,
)

# --- Nombres de colas
Q_EVT_FABRICATION_CANCELED = "evt_fabrication_canceled_queue"
Q_REFUND_RESULT = "refund_result_queue"


# =============================================================================
# Helpers internos
# =============================================================================
#region 0. HELPERS
def _safe_json_loads(raw: bytes) -> Optional[Dict[str, Any]]:
    """
    Parseo JSON robusto.

    Evita que un mensaje malformado tumbe el consumer.
    """
    try:
        return json.loads(raw)
    except Exception:
        logger.exception("[ORDER] ❌ Mensaje no es JSON válido: %r", raw)
        return None


def _get_cancel_saga_manager():
    """
    Import diferido para evitar ciclos de import (muy típico en SAGA + state machine).
    """
    from saga.state_machine.order_cancel_saga_manager import cancel_saga_manager
    return cancel_saga_manager


# =============================================================================
# Publishers (comandos)
# =============================================================================
#region 1. PUBLISHERS
async def publish_cancel_fabrication_command(order_id: int, saga_id: str) -> None:
    """
    Ordena a Warehouse cancelar la fabricación de un pedido.

    Publica:
        routing_key = cmd.cancel_fabrication
        exchange    = exchange_command
        payload     = {"order_id": int, "saga_id": str}
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_command(channel)

        payload = {"order_id": int(order_id), "saga_id": str(saga_id)}
        msg = Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=2,
        )

        await exchange.publish(msg, routing_key=RK_CMD_CANCEL_MFG)
        logger.info("[ORDER] 📤 %s → %s", RK_CMD_CANCEL_MFG, payload)
    finally:
        await connection.close()


async def publish_refund_command(order_id: int, user_id: int, saga_id: str) -> None:
    """
    Ordena a Payment devolver dinero (refund) tras cancelar fabricación.

    Publica:
        routing_key = cmd.refund
        exchange    = exchange_command
        payload     = {"order_id": int, "user_id": int, "saga_id": str}
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_command(channel)

        payload = {"order_id": int(order_id), "user_id": int(user_id), "saga_id": str(saga_id)}
        msg = Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=2,
        )

        await exchange.publish(msg, routing_key=RK_CMD_REFUND)
        logger.info("[ORDER] 📤 %s → %s", RK_CMD_REFUND, payload)
    finally:
        await connection.close()


# =============================================================================
# Consumers (eventos)
# =============================================================================
#region 2. CONSUMERS
async def _handle_evt_fabrication_canceled(message) -> None:
    """
    Traduce evt.fabrication_canceled a evento interno del CancelSaga.

    Espera (mínimo):
        {"saga_id": "...", "order_id": ...}

    Efecto:
        - Si existe saga activa => saga.on_event_saga({"type": "fabrication_canceled"})
        - Si no existe => warning (evento tardío/duplicado)
    """
    async with message.process():
        data = _safe_json_loads(message.body)
        if not data:
            return

        saga_id = data.get("saga_id")
        if not saga_id:
            logger.warning("[ORDER] %s sin saga_id: %s", RK_EVT_MFG_CANCELED, data)
            return

        cancel_saga_manager = _get_cancel_saga_manager()
        saga = cancel_saga_manager.get_saga(saga_id)

        if saga is None:
            logger.warning("[ORDER] No hay cancel_saga activa para saga_id=%s (evento tardío/duplicado)", saga_id)
            return

        await saga.on_event_saga({"type": "fabrication_canceled"})


async def listen_evt_fabrication_canceled() -> None:
    """
    Escucha confirmación de cancelación desde Warehouse.

    Cola:
        Q_EVT_FABRICATION_CANCELED
    Bindings:
        evt.fabrication_canceled
    Exchange:
        exchange_saga (eventos del saga)
    """
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)

    queue = await channel.declare_queue(Q_EVT_FABRICATION_CANCELED, durable=True)
    await queue.bind(exchange, routing_key=RK_EVT_MFG_CANCELED)
    await queue.consume(_handle_evt_fabrication_canceled)

    logger.info("[ORDER] 🟢 Escuchando %s (queue=%s)", RK_EVT_MFG_CANCELED, Q_EVT_FABRICATION_CANCELED)
    await asyncio.Future()

#region 2.1 refund meney
async def _handle_refund_result(message) -> None:
    """
    Traduce refund.result a evento interno del CancelSaga.

    Espera (mínimo):
        {"saga_id": "...", "status": "refunded|...", "reason": "...?"}

    Efecto:
        - refunded     -> saga.on_event_saga({"type":"refunded"})
        - otro status  -> saga.on_event_saga({"type":"refund_failed","reason":...})
    """
    async with message.process():
        data = _safe_json_loads(message.body)
        if not data:
            return

        saga_id = data.get("saga_id")
        status = (data.get("status") or "").strip().lower()
        reason = data.get("reason")

        if not saga_id:
            logger.warning("[ORDER] %s sin saga_id: %s", RK_EVT_REFUND_RESULT, data)
            return

        cancel_saga_manager = _get_cancel_saga_manager()
        saga = cancel_saga_manager.get_saga(saga_id)

        if saga is None:
            logger.warning("[ORDER] No hay cancel_saga activa para saga_id=%s (evento tardío/duplicado)", saga_id)
            return

        if status == "refunded":
            await saga.on_event_saga({"type": "refunded"})
        else:
            await saga.on_event_saga({"type": "refund_failed", "reason": reason or "unknown"})


async def listen_refund_result() -> None:
    """
    Escucha eventos de refund desde Payment.

    IMPORTANTE:
        - Un queue.bind solo acepta UNA routing_key (str).
          Por eso iteramos RK_EVT_REFUND_EVENTS.

    Cola:
        Q_REFUND_RESULT
    Bindings:
        refund.result, evt_refunded, evt_refund_failed (compatibilidad)
    Exchange:
        exchange_saga
    """
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)

    queue = await channel.declare_queue(Q_REFUND_RESULT, durable=True)

    # FIX: bind de múltiples routing keys (antes se pasaba una tupla, eso está mal).
    for rk in RK_EVT_REFUND_EVENTS:
        await queue.bind(exchange, routing_key=rk)

    await queue.consume(_handle_refund_result)

    logger.info("[ORDER] 🟢 Escuchando refund events=%s (queue=%s)", RK_EVT_REFUND_EVENTS, Q_REFUND_RESULT)
    await asyncio.Future()
