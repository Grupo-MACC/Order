# -*- coding: utf-8 -*-
"""
Broker / integración RabbitMQ del microservicio Order.

Objetivo del módulo:
    - Consumir eventos desde otros microservicios (Payment, Delivery, Warehouse, Auth).
    - Publicar comandos/eventos a otros microservicios (Warehouse, Delivery, Logger).
    - Mantener el acoplamiento a routing keys y colas bajo control.
"""

import asyncio
import httpx
import json
import logging
import os
from aio_pika import Message

from microservice_chassis_grupo2.core.rabbitmq_core import (
    PUBLIC_KEY_PATH,
    declare_exchange,
    declare_exchange_logs,
    get_channel,
)
from microservice_chassis_grupo2.core.consul import get_service_url
from services import order_service
from sql import models

logger = logging.getLogger(__name__)

# =============================================================================
# Constantes RabbitMQ (routing keys / colas / topics)
# =============================================================================

# --- Routing keys: Payment (eventos legacy)
RK_PAYMENT_PAID = "payment.paid"
RK_PAYMENT_FAILED = "payment.failed"

# --- Routing keys: Order (eventos internos)
RK_ORDER_CREATED = "order.confirmed"
RK_ORDER_FABRICATED = "order.fabricated"

# --- Routing keys: Delivery
RK_DELIVERY_READY = "delivery.finished"

# --- Routing keys: Auth (estado del servicio)
RK_AUTH_RUNNING = "auth.running"
RK_AUTH_NOT_RUNNING = "auth.not_running"

RK_WAREHOUSE_FABRICATION_COMPLETED = "warehouse.fabrication.completed"

# --- Routing keys: Logger (se usa el topic recibido)
#     No definimos constantes aquí porque el topic se construye dinámicamente:
#     "order.info", "order.error", "order.debug", etc.

# --- Nombres de colas
Q_PAYMENT_PAID = "order_paid_queue"
Q_PAYMENT_FAILED = "order_failed_queue"

Q_DELIVERY_READY = "delivery_ready_queue"

Q_AUTH_EVENTS = "order_queue"

Q_WAREHOUSE_EVENTS = "warehouse_events_queue"

# --- Warehouse binding (env var + default)
ENV_WAREHOUSE_EVENTS_BINDING = "WAREHOUSE_EVENTS_BINDING"
DEFAULT_WAREHOUSE_EVENTS_BINDING = "warehouse.#"

# --- Topics para logger ---
TOPIC_INFO = "order.info"
TOPIC_ERROR = "order.error"
TOPIC_DEBUG = "order.debug"

# =============================================================================
# Helpers internos
# =============================================================================
#region 0. HELPERS
def _normalize_fabrication_status(raw: str) -> str:
    """
    Normaliza estados de fabricación provenientes de Warehouse.

    Reglas:
        - Acepta variantes típicas (mayúsculas, guiones, espacios).
        - Devuelve SIEMPRE uno de los estados internos de models.Order:
            * MFG_REQUESTED, MFG_IN_PROGRESS, MFG_COMPLETED, MFG_FAILED

    Ejemplos:
        - "completed", "done" -> Completed
        - "in_progress", "working" -> InProgress
        - "failed", "error" -> Failed
    """
    if not raw:
        # Si no viene status, asumimos que no podemos decidir nada útil.
        return models.Order.MFG_IN_PROGRESS

    v = str(raw).strip().lower().replace("-", "_").replace(" ", "_")

    # Completed
    if v in {"completed", "complete", "done", "finished", "fabricated"}:
        return models.Order.MFG_COMPLETED
    # In progress
    if v in {"in_progress", "inprogress", "working", "manufacturing", "fabricating", "running"}:
        return models.Order.MFG_IN_PROGRESS
    # Requested
    if v in {"requested", "request", "queued", "pending", "created"}:
        return models.Order.MFG_REQUESTED
    # Failed
    if v in {"failed", "error", "ko", "rejected"}:
        return models.Order.MFG_FAILED

    # Fallback conservador: si no lo reconoces, NO marques completed.
    return models.Order.MFG_IN_PROGRESS


def _internal_ca_file() -> str:
    """
    Devuelve la ruta del CA bundle para llamadas internas HTTPS.

    Por qué:
        - Los microservicios están usando certificados firmados por una CA privada.
        - httpx por defecto valida contra el bundle del sistema/certifi.
        - Si no le pasas tu CA, obtendrás CERTIFICATE_VERIFY_FAILED.

    Prioridad:
        1) INTERNAL_CA_FILE
        2) CONSUL_CA_FILE
        3) /certs/ca.pem (convención del proyecto)
    """
    return os.getenv("INTERNAL_CA_FILE") or os.getenv("CONSUL_CA_FILE") or "/certs/ca.pem"

async def _download_auth_public_key(auth_base_url: str) -> str:
    """
    Descarga la clave pública de Auth usando HTTPS con verificación por CA privada.

    Args:
        auth_base_url: Base URL (p.ej. "https://auth:5004")

    Returns:
        El texto PEM de la clave pública.

    Nota:
        - Separar esta función facilita reintentos.
    """
    async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
        resp = await client.get(f"{auth_base_url}/auth/public-key")
        resp.raise_for_status()
        return resp.text


async def _ensure_auth_public_key(max_attempts: int = 20, base_delay: float = 0.25) -> None:
    """
    Asegura que existe la clave pública de Auth en PUBLIC_KEY_PATH.

    Estrategia simple:
        - Intenta resolver Auth por Consul (passing=true).
        - Si aún no hay instancias passing (race al arrancar), reintenta con backoff.
        - Cuando lo resuelve, descarga la clave con TLS verify (CA privada) y la guarda.

    Por qué:
        - auth.running se publica antes de que Auth esté realmente "ready" (FastAPI aún no sirve HTTP).
        - Por tanto, al recibir el evento, Consul puede devolver 0 passing temporalmente.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            auth_base_url = await get_service_url("auth")
            public_key = await _download_auth_public_key(auth_base_url)

            # Escritura directa (simple). Si quieres más robustez: escribir a .tmp y renombrar.
            with open(PUBLIC_KEY_PATH, "w", encoding="utf-8") as f:
                f.write(public_key)

            logger.info("[ORDER] ✅ Clave pública de Auth guardada en %s", PUBLIC_KEY_PATH)
            return

        except Exception as exc:
            # OJO: esto NO es un error grave. Es normal durante el arranque.
            logger.warning(
                "[ORDER] ⏳ Auth aún no está 'passing' o no responde. Reintento %s/%s. Motivo: %s",
                attempt, max_attempts, exc
            )

            # Backoff suave (capado)
            delay = min(2.0, base_delay * (2 ** (attempt - 1)))
            await asyncio.sleep(delay)

    raise RuntimeError("No se pudo obtener la clave pública de Auth tras varios reintentos.")


# =============================================================================
# Payment (legacy)
# =============================================================================
#region 1. PAYMENT
async def handle_payment_paid(message) -> None:
    """
    LEGACY: si se usa payment.paid/payment.failed fuera de la saga.

    Efecto:
        - No dispara fabricación.
        - Solo actualiza creation_status a CREATION_PAID.
    """
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]

        await order_service.update_order_creation_status(
            order_id=order_id,
            status=models.Order.CREATION_PAID,
        )
        logger.info("[ORDER] (legacy) %s → order=%s", RK_PAYMENT_PAID, order_id)


async def handle_payment_failed(message) -> None:
    """
    Handler legacy del fallo de pago.

    Nota:
        - Mantengo la lógica existente:
          log + publish_to_logger + update_order_status(...)
        - No cambia el contrato de mensaje.
    """
    async with message.process():
        data = json.loads(message.body)
        error_message = data["message"]
        order_id = data["order_id"]
        status = data["status"]

        logger.info("message: %s", error_message)
        logger.info("[ORDER] ❌ Pago fallido para orden: %s", data)

        await publish_to_logger(
            message={"message": f"Pago fallido para orden: {data}!❌"},
            topic=TOPIC_ERROR,
        )

        await order_service.update_order_status(order_id=order_id, status=status)


async def consume_payment_events() -> None:
    """
    Declara las colas legacy de Payment y se suscribe a sus eventos.

    Colas:
        - Q_PAYMENT_PAID  <- RK_PAYMENT_PAID
        - Q_PAYMENT_FAILED <- RK_PAYMENT_FAILED
    """
    _, channel = await get_channel()
    exchange = await declare_exchange(channel)

    order_paid_queue = await channel.declare_queue(Q_PAYMENT_PAID, durable=True)
    order_failed_queue = await channel.declare_queue(Q_PAYMENT_FAILED, durable=True)

    await order_paid_queue.bind(exchange, routing_key=RK_PAYMENT_PAID)
    await order_failed_queue.bind(exchange, routing_key=RK_PAYMENT_FAILED)

    await order_paid_queue.consume(handle_payment_paid)
    await order_failed_queue.consume(handle_payment_failed)

    logger.info("[ORDER] 🟢 Escuchando eventos legacy de Payment...")
    await asyncio.Future()


# =============================================================================
# Order -> Warehouse (comando mínimo)
# =============================================================================
#region 2. ORDER FABRIC
async def publish_do_order(order_id: int, number_of_pieces: int, pieces_a: int, pieces_b: int) -> None:
    """
    Publica el comando mínimo hacia Warehouse usando routing_key=order.confirmed.

    Importante:
        - Aunque el nombre de función sugiere "do_order", el contrato actual
          utiliza RK_ORDER_CREATED como routing_key (se mantiene).
        - Mantengo headers/content_type/delivery_mode tal cual estaban.
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange(channel)

        payload = {
            "order_id": order_id,
            "number_of_pieces": int(number_of_pieces),
            "pieces_a": int(pieces_a),
            "pieces_b": int(pieces_b),
        }

        msg = Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            headers={"event": RK_ORDER_CREATED},
            delivery_mode=2,
        )

        await exchange.publish(msg, routing_key=RK_ORDER_CREATED)
        logger.info("[ORDER] 📤 %s → %s", RK_ORDER_CREATED, payload)
    finally:
        await connection.close()


# =============================================================================
# Order Created (evento hacia delivery / logs)
# =============================================================================
#region 3. ORDER FABRICATED
async def publish_order_fabricated(order_id: int, number_of_pieces: int, user_id: int) -> None:
    """
    Publica el evento order.fabricated (usado por otros microservicios, p.ej. Delivery).

    Mantiene exactamente el payload original:
        {"order_id", "number_of_pieces", "user_id", "message"}
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange(channel)

        payload = {
            "order_id": order_id,
            "number_of_pieces": number_of_pieces,
            "user_id": user_id,
            "message": "Orden creada",
        }

        await exchange.publish(
            Message(body=json.dumps(payload).encode()),
            routing_key=RK_ORDER_FABRICATED,
        )

        logger.info("[ORDER] 📤 Publicado evento %s → %s", RK_ORDER_FABRICATED, order_id)

        await publish_to_logger(
            message={"message": f"📤 Publicado evento {RK_ORDER_FABRICATED} → {order_id}"},
            topic="order.debug",
        )
    finally:
        await connection.close()


# =============================================================================
# Delivery
# =============================================================================
#region 4. DELIVERY
async def consume_delivery_events() -> None:
    """
    Declara la cola de Delivery y consume eventos de entrega.

    Cola:
        - Q_DELIVERY_READY <- RK_DELIVERY_READY
    """
    _, channel = await get_channel()
    exchange = await declare_exchange(channel)

    delivery_ready_queue = await channel.declare_queue(Q_DELIVERY_READY, durable=True)
    await delivery_ready_queue.bind(exchange, routing_key=RK_DELIVERY_READY)

    await delivery_ready_queue.consume(handle_delivery_ready)

    # Log corregido (antes decía "pago", pero esto es delivery).
    logger.info("[ORDER] 🟢 Escuchando eventos de entrega...")
    await publish_to_logger(
        message={"message": "🟢 Escuchando eventos de entrega..."},
        topic="order.info",
    )

    await asyncio.Future()


async def handle_delivery_ready(message) -> None:
    """
    Actualiza el delivery_status cuando Delivery confirma que la entrega está lista/realizada.

    Nota:
        - Antes se llamaba update_order_status() (ya no existe).
        - Ahora se actualiza el campo delivery_status.
    """
    async with message.process():
        data = json.loads(message.body)
        order_id = data["order_id"]
        status = data["status"]

        await order_service.update_order_delivery_status(order_id=order_id, status=status)

        if models.Order.DELIVERY_DELIVERED == status:
            logger.info("[ORDER] 🚚 %s → order_id=%s status=%s", RK_DELIVERY_READY, order_id, status)

        await publish_to_logger(
            message={"message": f"🚚 Delivery status actualizado: order={order_id} status={status}"},
            topic="order.info",
        )


# =============================================================================
# Auth
# =============================================================================
#region 5. AUTH
async def consume_auth_events() -> None:
    """
    Consume eventos sobre el estado de Auth.

    Cola:
        - Q_AUTH_EVENTS <- RK_AUTH_RUNNING
        - Q_AUTH_EVENTS <- RK_AUTH_NOT_RUNNING

    Nota:
        - Se usa una única cola con 2 bindings, como estaba.
    """
    _, channel = await get_channel()
    exchange = await declare_exchange(channel)

    order_queue = await channel.declare_queue(Q_AUTH_EVENTS, durable=True)
    await order_queue.bind(exchange, routing_key=RK_AUTH_RUNNING)
    await order_queue.bind(exchange, routing_key=RK_AUTH_NOT_RUNNING)

    await order_queue.consume(handle_auth_events)

    logger.info("[ORDER] 🟢 Escuchando eventos de Auth (%s / %s)...", RK_AUTH_RUNNING, RK_AUTH_NOT_RUNNING)
    await asyncio.Future()


async def handle_auth_events(message) -> None:
    """
    Gestiona eventos de auth.running / auth.not_running.

    Nota importante:
        - Aunque recibamos 'running', Auth puede no estar listo aún (FastAPI aún no sirve HTTP).
        - Por eso hacemos reintentos contra Consul (passing=true) y luego descargamos la clave.
    """
    async with message.process():
        data = json.loads(message.body)
        if data.get("status") != "running":
            return

        try:
            await _ensure_auth_public_key()
            await publish_to_logger(
                message={"message": "Clave pública guardada", "path": PUBLIC_KEY_PATH},
                topic=TOPIC_INFO,
            )
        except Exception as exc:
            logger.error("[ORDER] ❌ Error obteniendo clave pública: %s", exc)
            await publish_to_logger(
                message={"message": "Error clave pública", "error": str(exc)},
                topic=TOPIC_ERROR,
            )


# =============================================================================
# Warehouse (publisher legacy + consumer de eventos)
# =============================================================================
#region 6. WAREHOUSE
async def consume_warehouse_events() -> None:
    """
    Declara una cola para eventos de Warehouse y los consume.

    Config:
        - ENV_WAREHOUSE_EVENTS_BINDING: binding key para el exchange
          (por defecto DEFAULT_WAREHOUSE_EVENTS_BINDING).

    Mantengo el comportamiento:
        - Cola fija Q_WAREHOUSE_EVENTS
        - Binding variable por env
    """
    _, channel = await get_channel()
    exchange = await declare_exchange(channel)

    binding = os.getenv(ENV_WAREHOUSE_EVENTS_BINDING, DEFAULT_WAREHOUSE_EVENTS_BINDING)

    queue = await channel.declare_queue(Q_WAREHOUSE_EVENTS, durable=True)
    await queue.bind(exchange, routing_key=binding)
    await queue.consume(handle_warehouse_event)

    logger.info("[ORDER] 🟢 Escuchando eventos de Warehouse con binding=%s", binding)

    await publish_to_logger(
        message={"message": f"🟢 Escuchando eventos de Warehouse ({binding})"},
        topic=TOPIC_INFO,
    )

    await asyncio.Future()


async def handle_warehouse_event(message) -> None:
    """
    Consume eventos de Warehouse y, cuando la fabricación termina,
    dispara el flujo de Delivery publicando `order.fabricated`.

    Payload esperado:
        - order_id: int
        - status o fabrication_status: str (p.ej. "completed")

    Reglas:
        - Actualiza `fabrication_status` en BD.
        - Si transiciona a COMPLETED:
            - Publica `order.fabricated` (evento que Delivery consume).
        - Idempotencia:
            - Si ya estaba COMPLETED, no republica.
            - Si delivery ya no está en NOT_STARTED, no republica.
        - Robustez:
            - No usa objetos ORM devueltos por crud después de hacer awaits.
            - Captura valores primitivos primero.
    """
    async with message.process():
        try:
            data = json.loads(message.body)
        except Exception:
            logger.exception("[ORDER] ❌ Evento de Warehouse no es JSON válido: %r", message.body)
            return

        order_id = data.get("order_id")
        if not order_id:
            logger.warning("[ORDER] Evento warehouse ignorado (sin order_id): %s", data)
            return

        raw_status = data.get("status") or data.get("fabrication_status")
        new_status = _normalize_fabrication_status(raw_status)

        # 1) Lee estado actual (y CAPTURA PRIMITIVOS antes de await extra)
        current = await order_service.get_order_by_id(int(order_id))
        if not current:
            logger.warning("[ORDER] Evento warehouse para order inexistente: order_id=%s payload=%s", order_id, data)
            return

        prev_fab_status = current.fabrication_status
        prev_delivery_status = current.delivery_status

        # Captura primitivos que necesitarás para publicar
        order_id_int = int(current.id)
        num_pieces = int(current.number_of_pieces)
        user_id = int(current.client_id)

        # 2) Persiste el nuevo estado de fabricación
        await order_service.update_order_fabrication_status(
            order_id=order_id_int,
            status=new_status,
        )

        logger.info(
            "[ORDER] 🏭 warehouse.fabrication.* → order=%s fabrication_status=%s (prev=%s)",
            order_id_int, new_status, prev_fab_status
        )

        # 3) Enganche con Delivery: SOLO si acabas de llegar a COMPLETED
        if new_status == models.Order.MFG_COMPLETED:
            # Idempotencia por fabricación
            if prev_fab_status == models.Order.MFG_COMPLETED:
                logger.info("[ORDER] ✅ Completed duplicado (no republish): order=%s", order_id_int)
                return

            # Idempotencia por delivery (si ya arrancó por cualquier motivo)
            if prev_delivery_status != models.Order.DELIVERY_NOT_STARTED:
                logger.info(
                    "[ORDER] ✅ Fabricación completed pero delivery ya inició (no republish): order=%s delivery=%s",
                    order_id_int, prev_delivery_status
                )
                return

            # Publica evento que dispara Delivery
            await publish_order_fabricated(
                order_id=order_id_int,
                number_of_pieces=num_pieces,
                user_id=user_id,
            )

            # IMPORTANTE: no uses `db_order.id` aquí.
            await publish_to_logger(
                message={"message": f"📤 {RK_ORDER_FABRICATED} publicado tras fabricación: order={order_id_int}"},
                topic=TOPIC_INFO,
            )




# =============================================================================
# Logger
# =============================================================================
#region 7. LOGGER
async def publish_to_logger(message: dict, topic: str) -> None:
    """
    Publica un log estructurado hacia el exchange de logs.

    Args:
        message:
            Diccionario con campos extra para el log (p.ej. {"message": "..."}).
        topic:
            Routing key del logger (p.ej. "order.info", "order.error", "order.debug").

    Contrato:
        - Se generan campos estándar:
            measurement="logs"
            service="order"
            severity="info|error|debug"
        - Se mezclan con el diccionario recibido en `message`.
    """
    connection = None
    try:
        connection, channel = await get_channel()
        exchange = await declare_exchange_logs(channel)

        log_data = {
            "measurement": "logs",
            "service": topic.split(".")[0],
            "severity": topic.split(".")[1] if "." in topic else "info",
            **message,
        }

        msg = Message(
            body=json.dumps(log_data).encode(),
            content_type="application/json",
            delivery_mode=2,
        )

        await exchange.publish(message=msg, routing_key=topic)

    except Exception as exc:
        # Mantengo el comportamiento de fallback por consola, como estaba.
        print(f"Error publishing to logger: {exc}")
    finally:
        if connection:
            await connection.close()