"""Modèle ``RelayEvent`` : journal des déclenchements du relais."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import Base

# Sources autorisées pour un déclenchement de relais.
RELAY_SOURCE_CALL = "call"
RELAY_SOURCE_SMS = "sms"
RELAY_SOURCE_MANUAL = "manual"
RELAY_SOURCES = (RELAY_SOURCE_CALL, RELAY_SOURCE_SMS, RELAY_SOURCE_MANUAL)


class RelayEvent(Base):
    """Un déclenchement du relais, quelle qu'en soit l'origine.

    ``source`` distingue ``"call"`` / ``"sms"`` / ``"manual"``.
    ``event_metadata`` (colonne ``metadata``) stocke des informations libres
    au format JSON (ex : commande SMS reçue, index SIM, opérateur…).
    Le nom d'attribut Python est ``event_metadata`` car ``metadata`` est
    réservé par SQLAlchemy sur les classes declaratives.
    """

    __tablename__ = "relay_events"

    id = Column(Integer, primary_key=True)

    phone_id = Column(
        Integer,
        ForeignKey("phones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    source = Column(String(16), default=RELAY_SOURCE_MANUAL, nullable=False, index=True)
    triggered_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    duration = Column(Float, nullable=True)  # durée d'impulsion en secondes

    event_metadata = Column("metadata", Text, nullable=True)

    phone = relationship("Phone", back_populates="relay_events")

    # ------------------------------------------------------------------ #
    # Helpers metadata JSON
    # ------------------------------------------------------------------ #
    def set_metadata(self, data: Optional[Dict[str, Any]]) -> None:
        """Sérialise un dictionnaire en JSON dans ``event_metadata``."""
        self.event_metadata = None if data is None else json.dumps(data, ensure_ascii=False)

    def get_metadata(self) -> Dict[str, Any]:
        """Retourne le contenu ``event_metadata`` désérialisé (``{}`` si vide)."""
        if not self.event_metadata:
            return {}
        try:
            return json.loads(self.event_metadata)
        except (ValueError, TypeError):
            return {}

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<RelayEvent {self.source} phone_id={self.phone_id} "
            f"@{self.triggered_at:%Y-%m-%d %H:%M:%S}>"
        )
