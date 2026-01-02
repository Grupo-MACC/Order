# -*- coding: utf-8 -*-
"""Clases Pydantic para Request/Response.

Puntos clave del refactor:
    - Se elimina el modelo de `Piece` (order ya no gestiona piezas individuales).
    - Se introduce el modelo de piezas por cantidad: `pieces_a` y `pieces_b`.
    - Se añade un DTO mínimo para publicar a warehouse: `WarehouseOrderCommand`.

Nota:
    - El `number_of_pieces` se calcula como (pieces_a + pieces_b) al persistir.
      Lo mantenemos en respuestas para compatibilidad y para facilitar cálculos
      en otros microservicios (pago, métricas, etc.).
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class Message(BaseModel):
    """Esquema genérico de mensaje."""
    detail: Optional[str] = Field(example="error or success message")


class OrderBase(BaseModel):
    """Campos base de una Order."""
    pieces_a: int = Field(description="Cantidad de piezas tipo A a fabricar", ge=0, example=3, default=0)
    pieces_b: int = Field(description="Cantidad de piezas tipo B a fabricar", ge=0, example=2, default=0)
    description: str = Field(description="Descripción humana del pedido", default="No description", example="Pedido A/B")
    address: Optional[str] = Field(description="Dirección de entrega", default=None, example="Calle X, España")


class OrderPost(OrderBase):
    """Schema de entrada para crear un pedido."""


class Order(OrderBase):
    """Schema de salida para un pedido."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int = Field(description="Id del pedido", example=1)
    user_id: int = Field(
        description="Id del usuario/cliente (auth)",
        example=7,
        validation_alias="client_id",
        serialization_alias="user_id",
    )

    number_of_pieces: int = Field(description="Total de piezas (A+B)", example=5)

    creation_status: str = Field(description="Estado creación (saga)", example="Paid")
    manufacturing_status: str = Field(description="Estado fabricación (warehouse)", example="Requested")
    delivery_status: str = Field(description="Estado entrega (delivery)", example="NotStarted")


class OrderStatusResponse(BaseModel):
    """Respuesta del endpoint /order/{id}/status."""
    order_id: int = Field(example=1)
    creation_status: str = Field(example="Confirmed")
    manufacturing_status: str = Field(example="Requested")
    delivery_status: str = Field(example="NotStarted")
    overall_status: str = Field(example="Manufacturing:Requested")


class WarehouseOrderCommand(BaseModel):
    """DTO mínimo publicado hacia warehouse.

    Importante:
        Warehouse NO necesita description/address/user_id para fabricar/stock.
        Solo necesita order_id y cantidades.
    """
    order_id: int
    number_of_pieces: int
    pieces_a: int
    pieces_b: int
