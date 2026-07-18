"""Modèle ``CallHistory`` : journal des appels (et des SMS de commande)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class CallHistory(Base):
    """Entrée d'historique pour un évènement entrant (appel ou SMS).

    Le champ ``source`` permet de distinguer un appel (``"call"``) d'une
    commande reçue par SMS (``"sms"``). Pour un appel non autorisé, on
    enregistre malgré tout la tentative avec ``authorized = answered =
    relay_triggered = False``.
    """

    __tablename__ = "call_history"

    id = Column(Integer, primary_key=True)

    phone_id = Column(
        Integer,
        ForeignKey("phones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    phone_number = Column(String(32), nullable=False, index=True)

    authorized = Column(Boolean, default=False, nullable=False)
    answered = Column(Boolean, default=False, nullable=False)
    relay_triggered = Column(Boolean, default=False, nullable=False)

    date = Column(DateTime, default=datetime.now, nullable=False, index=True)
    duration = Column(Float, nullable=True)  # durée d'appel en secondes

    # "call" | "sms"
    source = Column(String(16), default="call", nullable=False, index=True)

    phone = relationship("Phone", back_populates="call_history")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CallHistory {self.source} {self.phone_number!r} "
            f"auth={self.authorized} relay={self.relay_triggered} "
            f"@{self.date:%Y-%m-%d %H:%M:%S}>"
        )
