# -*- coding: utf-8 -*-
"""Database models definitions.

Este microservicio **order** ya no gestiona piezas individuales.

Resumen del cambio:
    - Antes: order creaba `Piece` (tabla `piece`) y publicaba `do.pieces` hacia machine.
    - Ahora: warehouse gestiona stock + fabricación y habla con machine.
    - Ahora: se puede cancelar un pedido en fabrication (antes no se podía).

Decisión de diseño:
    - Order solo almacena el pedido (cantidades) y estados.
    - Warehouse recibe un comando mínimo con:
        * order_id
        * number_of_pieces
        * pieces_a
        * pieces_b

Notas sobre estados:
    - Para no pisarte el estado cuando entren eventos de distintos procesos,
      separo los estados en tres campos:
        * creation_status: saga de creación (pago + delivery-check)
        * fabrication_status: lo que reporte warehouse
        * delivery_status: lo que reporte delivery

    - Dejo `status` como campo "legacy" (si ya hay consumidores externos).
      Si no lo necesitas, puedes eliminarlo y simplificar.
    
    - Se añaden estados de cancelación en fabrication_status para reflejar:
        * CANCELING (intermedio)
        * CANCELED (final OK)
        * CANCEL_PENDING_REFUND (final coherente si refund falla)
    - Se añade tabla CancelSaga para persistir saga_id y estado interno.
"""

from sqlalchemy import Column, Integer, String, TEXT
from microservice_chassis_grupo2.sql.models import BaseModel


class Order(BaseModel):
    """Order database table representation."""

    __tablename__ = "fabrication_order"

    # Estados (constantes recomendadas para evitar strings mágicos).
    CREATION_PENDING = "Pending"
    CREATION_PAID = "Paid"
    CREATION_CONFIRMED = "Confirmed"
    CREATION_NO_MONEY = "NoMoney"
    CREATION_NOT_DELIVERABLE = "NotDeliverable"
    CREATION_RETURNED = "Returned"

    MFG_NOT_STARTED = "NotStarted"
    MFG_REQUESTED = "Requested"
    MFG_IN_PROGRESS = "InProgress"
    MFG_COMPLETED = "Completed"
    MFG_FAILED = "Failed"

    DELIVERY_NOT_STARTED = "NotStarted"
    DELIVERY_READY = "Ready"
    DELIVERY_DELIVERED = "Delivered"
    DELIVERY_FAILED = "Failed"

    # --- CANCELATION: estados de cancelación (se guardan en fabrication_status) ---
    MFG_CANCELING = "Canceling"
    MFG_CANCELED = "Canceled"
    MFG_CANCEL_PENDING_REFUND = "CancelPendingRefund"

    id = Column(Integer, primary_key=True)

    # Identidad del cliente/usuario (del token auth).
    client_id = Column(Integer, nullable=False)

    # Datos de negocio.
    description = Column(TEXT, nullable=False, default="No description")
    address = Column(String(255), nullable=True)

    # Cantidades de piezas (nuevo modelo A/B).
    pieces_a = Column(Integer, nullable=False, default=0)
    pieces_b = Column(Integer, nullable=False, default=0)

    # Total redundante (A+B). Útil si otros servicios calculan importe con esto.
    number_of_pieces = Column(Integer, nullable=False, default=0)

    # Estados por fase.
    creation_status = Column(String(64), nullable=False, default=CREATION_PENDING)
    fabrication_status = Column(String(64), nullable=False, default=MFG_NOT_STARTED)
    delivery_status = Column(String(64), nullable=False, default=DELIVERY_NOT_STARTED)

    # Campo legacy (opcional). Manténlo hasta que migres consumidores.
    status = Column(String(256), nullable=False, default="Created")

    def as_dict(self):
        """Return the order item as dict.

        Nota:
            BaseModel.as_dict() ya incluye todas las columnas del modelo.
            Aquí no añadimos nada extra (antes se añadían `pieces`).
        """
        return super().as_dict()

class CancelSaga(BaseModel):
    """Persistencia del SAGA de cancelación.

    Por qué existe:
        - Correlación por saga_id (Rabbit puede reentregar, puedes reiniciar servicios, etc.)
        - Guardar estado interno y motivo de error si refund falla.

    Campos:
        saga_id: UUID string. Clave primaria.
        order_id: Pedido afectado.
        state: Estado interno (Canceling/Refunding/Canceled/CancelPendingRefund).
        error: Texto opcional con causa del fallo de refund.
    """

    __tablename__ = "cancel_saga"

    saga_id = Column(String(64), primary_key=True)
    order_id = Column(Integer, nullable=False)
    state = Column(String(64), nullable=False, default="Canceling")
    error = Column(TEXT, nullable=True)
