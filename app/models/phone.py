"""Modèle ``Phone`` : numéros de la whitelist."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin


class Phone(TimestampMixin, Base):
    """Numéro autorisé (ou non) à commander le garage.

    Un numéro appartient à la whitelist active uniquement si ``enabled`` est
    ``True``. Le champ ``number`` doit toujours être stocké sous sa forme
    normalisée (voir ``app.utils.phone_numbers.normalize_number``).
    """

    __tablename__ = "phones"

    id = Column(Integer, primary_key=True)
    number = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)

    # Relations inverses.
    call_history = relationship(
        "CallHistory",
        back_populates="phone",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    relay_events = relationship(
        "RelayEvent",
        back_populates="phone",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        state = "enabled" if self.enabled else "disabled"
        return f"<Phone {self.number!r} ({self.name or '-'}) {state}>"
