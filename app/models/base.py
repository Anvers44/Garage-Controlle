"""Base declarative SQLAlchemy et mixins communs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TimestampMixin:
    """Ajoute des colonnes ``created_at`` / ``updated_at`` gérées automatiquement.

    On utilise ``datetime.now`` (heure locale) et non ``utcnow`` car les
    rapports quotidiens et les statistiques journalières raisonnent sur la
    journée locale de l'utilisateur.
    """

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )
