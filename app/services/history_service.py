"""HistoryService : création et agrégation de l'historique des évènements."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from typing import List, Optional

from app.database import SessionFactory, session_scope
from app.models import CallHistory

logger = logging.getLogger(__name__)


@dataclass
class DailyStats:
    """Statistiques agrégées d'une journée (utilisées par le rapport)."""

    day: date
    total_calls: int = 0
    authorized_calls: int = 0
    call_openings: int = 0
    sms_openings: int = 0
    refused_attempts: int = 0


class HistoryService:
    """Écrit les entrées ``CallHistory`` et calcule les stats journalières."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    # Écriture
    # ------------------------------------------------------------------ #
    def record_call(
        self,
        phone_number: str,
        authorized: bool,
        answered: bool,
        relay_triggered: bool,
        duration: Optional[float] = None,
        phone_id: Optional[int] = None,
        source: str = "call",
        when: Optional[datetime] = None,
    ) -> CallHistory:
        """Crée une entrée d'historique (appel ou SMS).

        Returns:
            L'``CallHistory`` persisté (détaché de la session).
        """
        with session_scope(self._session_factory) as session:
            entry = CallHistory(
                phone_id=phone_id,
                phone_number=phone_number,
                authorized=authorized,
                answered=answered,
                relay_triggered=relay_triggered,
                duration=duration,
                source=source,
                date=when or datetime.now(),
            )
            session.add(entry)
            session.flush()
            session.expunge(entry)
            logger.debug(
                "Historique enregistré : %s %s auth=%s relay=%s",
                source,
                phone_number,
                authorized,
                relay_triggered,
            )
            return entry

    # ------------------------------------------------------------------ #
    # Lecture / agrégation
    # ------------------------------------------------------------------ #
    def list_recent(self, limit: int = 100) -> List[CallHistory]:
        with session_scope(self._session_factory) as session:
            return (
                session.query(CallHistory)
                .order_by(CallHistory.date.desc())
                .limit(limit)
                .all()
            )

    def get_daily_stats(self, day: date) -> DailyStats:
        """Agrège les statistiques d'une journée à partir de ``CallHistory``.

        - ``total_calls`` / ``authorized_calls`` : uniquement source ``call``.
        - ``call_openings`` / ``sms_openings`` : relais déclenché par source.
        - ``refused_attempts`` : tentatives non autorisées (appels + SMS).
        """
        start = datetime.combine(day, dt_time.min)
        end = datetime.combine(day, dt_time.max)

        stats = DailyStats(day=day)
        with session_scope(self._session_factory) as session:
            rows = (
                session.query(CallHistory)
                .filter(CallHistory.date >= start, CallHistory.date <= end)
                .all()
            )
            for row in rows:
                is_call = row.source == "call"
                if is_call:
                    stats.total_calls += 1
                    if row.authorized:
                        stats.authorized_calls += 1
                if row.relay_triggered:
                    if row.source == "sms":
                        stats.sms_openings += 1
                    else:
                        stats.call_openings += 1
                if not row.authorized:
                    stats.refused_attempts += 1
        return stats
