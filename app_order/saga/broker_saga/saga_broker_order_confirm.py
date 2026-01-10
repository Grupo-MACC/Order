# -*- coding: utf-8 -*-
"""
Broker RabbitMQ para el SAGA de confirmación de pedido (Order).

Responsabilidades:
    - Publicar comandos (exchange_command):
        * pay              -> Payment
        * check.delivery    -> Delivery
        * return.money      -> Payment (devolución)

    - Consumir resultados (exchange_saga):
        * payment.result    -> resultado de pago
        * delivery.result   -> resultado de comprobación de entrega
        * money.returned    -> confirmación de devolución

Notas de diseño:
    - Todas las routing keys y colas se definen como constantes en un único punto.
    - Los comandos se publican en exchange_command.
    - Los eventos del saga se consumen desde exchange_saga.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from aio_pika import Message

from microservice_chassis_grupo2.core.rabbitmq_core import (
    get_channel,
    declare_exchange_command,
    declare_exchange_saga,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Routing keys (único punto de control)
# =============================================================================

# --- Commands (publicados por Order)
RK_CMD_PAY = "pay"
RK_CMD_CHECK_DELIVERY = "check.delivery"
RK_CMD_RETURN_MONEY = "return.money"

# --- Saga events (consumidos por Order)
RK_EVT_PAYMENT_RESULT = "payment.result"
RK_EVT_DELIVERY_RESULT = "delivery.result"
RK_EVT_MONEY_RETURNED = "money.returned"

# --- Nombres de colas
Q_PAYMENT_RESULT = "payment_result_queue"
Q_DELIVERY_RESULT = "delivery_result_queue"
Q_MONEY_RETURNED = "money_returned_queue"


# =============================================================================
# Helpers internos
# =============================================================================
#region 0. HELPERS
def _safe_json_loads(raw: bytes) -> Optional[Dict[str, Any]]:
    """
    Parseo JSON robusto.

    Evita tumbar el consumer si llega un mensaje malformado.
    """
    try:
        return json.loads(raw)
    except Exception:
        logger.exception("[ORDER] ❌ Mensaje no es JSON válido: %r", raw)
        return None


def _get_confirm_saga_manager():
    """
    Import diferido para evitar ciclos de import con la state machine del SAGA.
    """
    from saga.state_machine.order_confirm_saga_manager import saga_manager
    return saga_manager


# =============================================================================
# Publishers (comandos)
# =============================================================================
#region 1. PUBLISHERS
async def publish_payment_command(order_data) -> None:
    """
    Publica un comando de pago hacia Payment.

    Payload (mantengo el original):
        {
          "order_id": order_data.id,
          "user_id": order_data.user_id,
          "number_of_pieces": order_data.number_of_pieces,
          "message": "Pay order"
        }
    Routing key:
        RK_CMD_PAY
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_command(channel)

        payload = {
            "order_id": order_data.id,
            "user_id": order_data.user_id,
            "number_of_pieces": order_data.number_of_pieces,
            "message": "Pay order",
        }

        await exchange.publish(
            Message(body=json.dumps(payload).encode(), content_type="application/json", delivery_mode=2),
            routing_key=RK_CMD_PAY,
        )

        logger.info("[ORDER] 📤 Enviando orden %s a pago...", order_data.id)
    finally:
        await connection.close()

#region 1.1 delivery check
async def publish_delivery_check_command(order_data) -> None:
    """
    Publica un comando para comprobar si la entrega es posible (Delivery).

    Payload (mantengo el original):
        {
          "order_id": order_data.id,
          "user_id": order_data.user_id,
          "address": order_data.address
        }
    Routing key:
        RK_CMD_CHECK_DELIVERY
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_command(channel)

        payload = {
            "order_id": order_data.id,
            "user_id": order_data.user_id,
            "address": order_data.address,
        }

        await exchange.publish(
            Message(body=json.dumps(payload).encode(), content_type="application/json", delivery_mode=2),
            routing_key=RK_CMD_CHECK_DELIVERY,
        )

        logger.info("[ORDER] 📤 Verificando entrega para orden %s...", order_data.id)
    finally:
        await connection.close()

#region 1.1 return money
async def publish_return_money_command(order_data) -> None:
    """
    Publica un comando para devolver el dinero (Payment).

    Payload (mantengo el original):
        {
          "order_id": order_data.id,
          "user_id": order_data.user_id
        }
    Routing key:
        RK_CMD_RETURN_MONEY
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_command(channel)

        payload = {"order_id": order_data.id, "user_id": order_data.user_id}

        await exchange.publish(
            Message(body=json.dumps(payload).encode(), content_type="application/json", delivery_mode=2),
            routing_key=RK_CMD_RETURN_MONEY,
        )

        logger.info("[ORDER] 📤 Solicitando devolución de dinero para orden %s...", order_data.id)
    finally:
        await connection.close()


# =============================================================================
# Handlers (eventos)
# =============================================================================
#region 2. HANDLERS
async def handle_payment_result(message) -> None:
    """
    Maneja el evento payment.result y lo traduce a evento interno del SAGA.

    Espera:
        {"order_id": ..., "status": "paid|not_paid|..."}
    Traducción:
        paid      -> {"type": "payment_accepted"}
        not_paid  -> {"type": "payment_rejected"}
        otro      -> se ignora (como antes), pero con warning.
    """
    async with message.process():
        data = _safe_json_loads(message.body)
        if not data:
            return

        status = (data.get("status") or "").strip().lower()
        order_id = data.get("order_id")

        if not order_id:
            logger.warning("[ORDER] %s sin order_id: %s", RK_EVT_PAYMENT_RESULT, data)
            return

        if status == "paid":
            event = {"type": "payment_accepted"}
        elif status == "not_paid":
            event = {"type": "payment_rejected"}
        else:
            logger.warning("[ORDER] ⚠️ Estado desconocido del pago: %s (order_id=%s)", status, order_id)
            return

        saga_manager = _get_confirm_saga_manager()
        saga = saga_manager.get_saga(order_id)

        if saga is None:
            logger.warning("[ORDER] No hay confirm_saga activa para order_id=%s (evento tardío/duplicado)", order_id)
            return

        await saga.on_event_saga(event)

#region 2.1 delivery result
async def handle_delivery_result(message) -> None:
    """
    Maneja el evento delivery.result y lo traduce a evento interno del SAGA.

    Espera:
        {"order_id": ..., "status": "deliverable|not_deliverable|..."}
    Traducción:
        deliverable      -> {"type": "delivery_possible"}
        not_deliverable  -> {"type": "delivery_not_possible"}
        otro             -> se ignora (como antes), pero con warning.
    """
    async with message.process():
        data = _safe_json_loads(message.body)
        if not data:
            return

        status = (data.get("status") or "").strip().lower()
        order_id = data.get("order_id")

        if not order_id:
            logger.warning("[ORDER] %s sin order_id: %s", RK_EVT_DELIVERY_RESULT, data)
            return

        if status == "deliverable":
            event = {"type": "delivery_possible"}
        elif status == "not_deliverable":
            event = {"type": "delivery_not_possible"}
        else:
            logger.warning("[ORDER] ⚠️ Estado desconocido de delivery: %s (order_id=%s)", status, order_id)
            return

        saga_manager = _get_confirm_saga_manager()
        saga = saga_manager.get_saga(order_id)

        if saga is None:
            logger.warning("[ORDER] No hay confirm_saga activa para order_id=%s (evento tardío/duplicado)", order_id)
            return

        await saga.on_event_saga(event)

#region 2.2 money returned
async def handle_money_returned(message) -> None:
    """
    Maneja el evento money.returned y notifica al SAGA.

    Espera:
        {"order_id": ...}
    Traducción:
        -> {"type": "money_returned"}
    """
    async with message.process():
        data = _safe_json_loads(message.body)
        if not data:
            return

        order_id = data.get("order_id")
        if not order_id:
            logger.warning("[ORDER] %s sin order_id: %s", RK_EVT_MONEY_RETURNED, data)
            return

        saga_manager = _get_confirm_saga_manager()
        saga = saga_manager.get_saga(order_id)

        if saga is None:
            logger.warning("[ORDER] No hay confirm_saga activa para order_id=%s (evento tardío/duplicado)", order_id)
            return

        await saga.on_event_saga({"type": "money_returned"})


# =============================================================================
# Listeners (setup colas + bindings)
# =============================================================================
#region 3. LISTENERS
async def listen_payment_result() -> None:
    """
    Suscribe a payment.result en exchange_saga usando Q_PAYMENT_RESULT.
    """
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)

    queue = await channel.declare_queue(Q_PAYMENT_RESULT, durable=True)
    await queue.bind(exchange, routing_key=RK_EVT_PAYMENT_RESULT)
    await queue.consume(handle_payment_result)

    logger.info("[ORDER] 🟢 Escuchando %s (queue=%s)", RK_EVT_PAYMENT_RESULT, Q_PAYMENT_RESULT)
    await asyncio.Future()


async def listen_delivery_result() -> None:
    """
    Suscribe a delivery.result en exchange_saga usando Q_DELIVERY_RESULT.
    """
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)

    queue = await channel.declare_queue(Q_DELIVERY_RESULT, durable=True)
    await queue.bind(exchange, routing_key=RK_EVT_DELIVERY_RESULT)
    await queue.consume(handle_delivery_result)

    logger.info("[ORDER] 🟢 Escuchando %s (queue=%s)", RK_EVT_DELIVERY_RESULT, Q_DELIVERY_RESULT)
    await asyncio.Future()


async def listen_money_returned_result() -> None:
    """
    Suscribe a money.returned en exchange_saga usando Q_MONEY_RETURNED.
    """
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)

    queue = await channel.declare_queue(Q_MONEY_RETURNED, durable=True)
    await queue.bind(exchange, routing_key=RK_EVT_MONEY_RETURNED)
    await queue.consume(handle_money_returned)

    logger.info("[ORDER] 🟢 Escuchando %s (queue=%s)", RK_EVT_MONEY_RETURNED, Q_MONEY_RETURNED)
    await asyncio.Future()
