# -*- coding: utf-8 -*-
"""Database models definitions. Table representations as class."""
from sqlalchemy import Column, DateTime, Integer, String, TEXT, ForeignKey
from sqlalchemy.orm import relationship
from microservice_chassis_grupo2.sql.models import BaseModel

class Order(BaseModel):
    """order database table representation."""
    STATUS_CREATED = "Created"
    STATUS_PAID = "Paid"
    STATUS_FINISHED = "Finished"
    STATUS_DELIVERED = "Delivered"
    __tablename__ = "manufacturing_order"
    id = Column(Integer, primary_key=True)
    number_of_pieces = Column(Integer, nullable=False)
    description = Column(TEXT, nullable=False, default="No description")
    client_id= Column(Integer, nullable=False)
    status = Column(String(256), nullable=False, default=STATUS_CREATED)
    address = Column(String(255), nullable=True)  # <-- new field

    pieces = relationship("Piece", back_populates="order", lazy="joined")

    def as_dict(self):
        """Return the order item as dict."""
        dictionary = super().as_dict()
        dictionary['pieces'] = [i.as_dict() for i in self.pieces]
        return dictionary


class Piece(BaseModel):
    """Piece database table representation."""
    STATUS_CREATED = "Created"
    STATUS_CANCELLED = "Cancelled"
    STATUS_QUEUED = "Queued"
    STATUS_MANUFACTURING = "Manufacturing"
    STATUS_MANUFACTURED = "Manufactured"

    __tablename__ = "piece"
    id = Column(Integer, primary_key=True)
    manufacturing_date = Column(DateTime(timezone=True), server_default=None)
    status = Column(String(256), default=STATUS_QUEUED)
    order_id = Column(
        Integer,
        ForeignKey('manufacturing_order.id', ondelete='cascade'),
        nullable=True)

    order = relationship('Order', back_populates='pieces', lazy="joined")
