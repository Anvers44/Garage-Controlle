"""Modèles SQLAlchemy du Garage Controller GSM.

Importer ce package suffit à enregistrer tous les modèles sur ``Base.metadata``
(utile avant ``Base.metadata.create_all``).
"""

from app.models.base import Base, TimestampMixin
from app.models.call_history import CallHistory
from app.models.phone import Phone
from app.models.relay_event import (
    RELAY_SOURCE_CALL,
    RELAY_SOURCE_MANUAL,
    RELAY_SOURCE_SMS,
    RELAY_SOURCES,
    RelayEvent,
)
from app.models.setting import Setting

__all__ = [
    "Base",
    "TimestampMixin",
    "Phone",
    "CallHistory",
    "RelayEvent",
    "Setting",
    "RELAY_SOURCE_CALL",
    "RELAY_SOURCE_SMS",
    "RELAY_SOURCE_MANUAL",
    "RELAY_SOURCES",
]
