"""Modèle ``Setting`` : stockage clé/valeur des paramètres applicatifs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.models.base import Base


class Setting(Base):
    """Paramètre applicatif simple (clé/valeur textuelle).

    Les valeurs sont toujours stockées sous forme de chaîne ; la conversion
    typée (bool, float, JSON…) est assurée par ``SettingsService``.
    """

    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Setting {self.key!r}={self.value!r}>"
