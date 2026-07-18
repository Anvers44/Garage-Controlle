"""RelayService : déclenchement du relais + journalisation ``RelayEvent``."""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time
from typing import Any, Dict, List, Optional

from app.database import SessionFactory, session_scope
from app.hardware.gpio import RelayDriver
from app.models import RELAY_SOURCES, RelayEvent

logger = logging.getLogger(__name__)


class RelayService:
    """Pilote le relais et journalise chaque déclenchement.

    Ce service ne connaît pas la logique d'autorisation : celle-ci est du
    ressort du ``GSMService``. Il se contente d'ouvrir (impulsion) et d'écrire
    un ``RelayEvent`` avec la ``source`` transmise.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        relay: RelayDriver,
        default_pulse_seconds: float = 0.5,
    ) -> None:
        self._session_factory = session_factory
        self._relay = relay
        self._default_pulse = default_pulse_seconds

    def trigger(
        self,
        source: str,
        duration: Optional[float] = None,
        phone_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RelayEvent:
        """Active le relais et enregistre un ``RelayEvent``.

        Args:
            source: ``"call"``, ``"sms"`` ou ``"manual"``.
            duration: durée d'impulsion (défaut si ``None``).
            phone_id: numéro à l'origine du déclenchement (si connu).
            metadata: informations libres (sérialisées en JSON).

        Returns:
            L'``RelayEvent`` persisté (détaché de la session).
        """
        if source not in RELAY_SOURCES:
            raise ValueError(f"Source de relais invalide : {source!r}")

        pulse = self._default_pulse if duration is None else float(duration)
        applied = self._relay.pulse(pulse)
        logger.info("Relais déclenché (source=%s, durée=%.3fs)", source, applied)

        with session_scope(self._session_factory) as session:
            event = RelayEvent(
                source=source,
                duration=applied,
                phone_id=phone_id,
                triggered_at=datetime.now(),
            )
            event.set_metadata(metadata)
            session.add(event)
            session.flush()
            session.expunge(event)
            return event

    # ------------------------------------------------------------------ #
    # Statistiques / lecture
    # ------------------------------------------------------------------ #
    def count_for_date(self, day: date, source: Optional[str] = None) -> int:
        """Nombre de déclenchements pour un jour donné (optionnellement filtré)."""
        start = datetime.combine(day, dt_time.min)
        end = datetime.combine(day, dt_time.max)
        with session_scope(self._session_factory) as session:
            query = session.query(RelayEvent).filter(
                RelayEvent.triggered_at >= start,
                RelayEvent.triggered_at <= end,
            )
            if source is not None:
                query = query.filter(RelayEvent.source == source)
            return query.count()

    def recent(self, limit: int = 50) -> List[RelayEvent]:
        with session_scope(self._session_factory) as session:
            return (
                session.query(RelayEvent)
                .order_by(RelayEvent.triggered_at.desc())
                .limit(limit)
                .all()
            )

    @property
    def is_active(self) -> bool:
        """État courant du relais (relayé depuis le driver)."""
        return self._relay.is_active
