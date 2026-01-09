# -*- coding: utf-8 -*-
"""Broker RabbitMQ para el SAGA de cancelación (Order).

Publica:
    - cmd.cancel_manufacturing → Warehouse
    - cmd.refund → Payment

Consume:
    - evt.manufacturing_canceled ← Warehouse
    - refund.result ← Payment
"""
import asyncio
import json
import logging
from aio_pika import Message
from microservice_chassis_grupo2.core.rabbitmq_core import (
    get_channel,
    declare_exchange,
    declare_exchange_command,
    declare_exchange_saga,
)

logger = logging.getLogger(__name__)


# =========================
# Routing keys
# =========================
RK_CMD_CANCEL_MFG = "cmd.cancel_manufacturing"
RK_EVT_MFG_CANCELED = "evt.manufacturing_canceled"

RK_CMD_REFUND = "cmd.refund"
RK_EVT_REFUND_EVENTS = ("refund.result", "evt_refunded", "evt_refund_failed")


# region Publishers
async def publish_cancel_manufacturing_command(order_id: int, saga_id: str):
    """Ordena a Warehouse cancelar la fabricación de un pedido."""
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange(channel)
        payload = {"order_id": int(order_id), "saga_id": str(saga_id)}
        msg = Message(body=json.dumps(payload).encode(), content_type="application/json", delivery_mode=2)
        await exchange.publish(msg, routing_key=RK_CMD_CANCEL_MFG)
        logger.info("[ORDER] 📤 %s → %s", RK_CMD_CANCEL_MFG, payload)
    finally:
        await connection.close()


async def publish_refund_command(order_id: int, user_id: int, saga_id: str):
    """Ordena a Payment devolver dinero (refund) tras cancelar fabricación."""
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_command(channel)
        payload = {"order_id": int(order_id), "user_id": int(user_id), "saga_id": str(saga_id)}
        msg = Message(body=json.dumps(payload).encode(), content_type="application/json", delivery_mode=2)
        await exchange.publish(msg, routing_key=RK_CMD_REFUND)
        logger.info("[ORDER] 📤 %s → %s", RK_CMD_REFUND, payload)
    finally:
        await connection.close()

# region Consumers
async def _handle_evt_mfg_canceled(message):
    """Traduce evt.manufacturing_canceled a evento interno del CancelSaga."""
    async with message.process():
        data = json.loads(message.body)
        saga_id = data.get("saga_id")
        if not saga_id:
            logger.warning("[ORDER] evt.manufacturing_canceled sin saga_id: %s", data)
            return

        from saga.state_machine.order_cancel_saga_manager import cancel_saga_manager
        saga = cancel_saga_manager.get_saga(saga_id)
        if saga is None:
            logger.warning("[ORDER] No hay cancel_saga activa para saga_id=%s (evento tardío/duplicado)", saga_id)
            return

        await saga.on_event_saga({"type": "manufacturing_canceled"})


async def listen_evt_manufacturing_canceled():
    """Escucha confirmación de cancelación desde Warehouse."""
    _, channel = await get_channel()
    exchange = await declare_exchange(channel)

    queue = await channel.declare_queue("evt_mfg_canceled_queue", durable=True)
    await queue.bind(exchange, routing_key=RK_EVT_MFG_CANCELED)
    await queue.consume(_handle_evt_mfg_canceled)

    logger.info("[ORDER] 🟢 Escuchando %s", RK_EVT_MFG_CANCELED)
    await asyncio.Future()


async def _handle_refund_result(message):
    """Traduce refund.result a evento interno del CancelSaga."""
    async with message.process():
        data = json.loads(message.body)
        saga_id = data.get("saga_id")
        status = (data.get("status") or "").lower()
        reason = data.get("reason")

        if not saga_id:
            logger.warning("[ORDER] refund.result sin saga_id: %s", data)
            return

        from saga.state_machine.order_cancel_saga_manager import cancel_saga_manager
        saga = cancel_saga_manager.get_saga(saga_id)
        if saga is None:
            logger.warning("[ORDER] No hay cancel_saga activa para saga_id=%s (evento tardío/duplicado)", saga_id)
            return

        if status == "refunded":
            await saga.on_event_saga({"type": "refunded"})
        else:
            await saga.on_event_saga({"type": "refund_failed", "reason": reason or "unknown"})


async def listen_refund_result():
    """Escucha refund.result desde Payment."""
    _, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)

    queue = await channel.declare_queue("refund_result_queue", durable=True)
    await queue.bind(exchange, routing_key=RK_EVT_REFUND_EVENTS)
    await queue.consume(_handle_refund_result)

    logger.info("[ORDER] 🟢 Escuchando %s", RK_EVT_REFUND_EVENTS)
    await asyncio.Future()
