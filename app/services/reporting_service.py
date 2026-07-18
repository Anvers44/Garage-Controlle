"""ReportingService + ReportingScheduler : rapport quotidien par SMS."""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from typing import List, Optional

from app.hardware.sim800 import SIM800, SIM800Error
from app.services.history_service import DailyStats, HistoryService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class ReportingService:
    """Construit et envoie le SMS de synthèse quotidienne."""

    def __init__(
        self,
        history_service: HistoryService,
        settings_service: SettingsService,
        sim800: SIM800,
    ) -> None:
        self._history = history_service
        self._settings = settings_service
        self._sim800 = sim800

    # ------------------------------------------------------------------ #
    # Construction du texte
    # ------------------------------------------------------------------ #
    def build_daily_report(self, day: date) -> str:
        """Retourne le texte du rapport pour ``day`` (voir docs/spec-sms.md).

        Le rapport reste court (idéalement <= 160 caractères).
        """
        stats: DailyStats = self._history.get_daily_stats(day)
        include_sms = self._settings.get_bool("report_include_sms", default=True)

        lines: List[str] = [
            f"[Garage] {day:%Y-%m-%d}",
            f"Appels: {stats.total_calls} ({stats.authorized_calls} autorises)",
            f"Ouvertures appel: {stats.call_openings}",
        ]
        if include_sms:
            lines.append(f"Ouvertures SMS: {stats.sms_openings}")
        lines.append(f"Tentatives refusees: {stats.refused_attempts}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Envoi
    # ------------------------------------------------------------------ #
    def get_recipients(self) -> List[str]:
        """Liste des destinataires du rapport (setting ``report_recipients``)."""
        return [r.strip() for r in self._settings.get_list("report_recipients") if r.strip()]

    def send_daily_report(self, day: Optional[date] = None) -> bool:
        """Construit puis envoie le rapport du jour à tous les destinataires.

        Returns:
            ``True`` si au moins un SMS a été envoyé, ``False`` sinon.
        """
        report_day = day or datetime.now().date()
        recipients = self.get_recipients()
        if not recipients:
            logger.warning("Rapport quotidien : aucun destinataire configuré.")
            return False

        text = self.build_daily_report(report_day)
        sent = 0
        for number in recipients:
            try:
                self._sim800.send_sms(number, text)
                sent += 1
            except SIM800Error:
                logger.exception("Rapport quotidien : envoi à %s échoué", number)

        logger.info(
            "Rapport quotidien %s envoyé à %d/%d destinataire(s)",
            report_day,
            sent,
            len(recipients),
        )
        return sent > 0


class ReportingScheduler:
    """Thread léger déclenchant ``send_daily_report`` une fois par jour.

    Le scheduler vérifie l'heure système à intervalle régulier. Lorsque l'heure
    courante atteint ou dépasse ``report_time`` et que le rapport du jour n'a pas
    encore été envoyé, il appelle ``send_daily_report`` (si ``report_enabled``).
    Il tourne côté backend, hors Flask.
    """

    def __init__(
        self,
        reporting_service: ReportingService,
        settings_service: SettingsService,
        check_interval_seconds: float = 30.0,
    ) -> None:
        self._reporting = reporting_service
        self._settings = settings_service
        self._interval = check_interval_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_sent_day: Optional[date] = None

    def start(self) -> None:
        """Démarre le thread du scheduler (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="reporting-scheduler", daemon=True
        )
        self._thread.start()
        logger.info("ReportingScheduler démarré (intervalle=%.0fs)", self._interval)

    def stop(self) -> None:
        """Arrête le thread du scheduler."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._interval + 1.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick(datetime.now())
            except Exception:  # pragma: no cover - ne doit jamais tuer le thread
                logger.exception("ReportingScheduler : erreur pendant le tick")
            self._stop.wait(self._interval)

    def _tick(self, now: datetime) -> None:
        """Évalue si le rapport doit être envoyé à l'instant ``now``."""
        if not self._settings.get_bool("report_enabled", default=False):
            return
        today = now.date()
        if self._last_sent_day == today:
            return  # déjà envoyé aujourd'hui

        target = self._parse_report_time(self._settings.get("report_time", "20:00"))
        if target is None:
            return
        if (now.hour, now.minute) >= target:
            if self._reporting.send_daily_report(today):
                self._last_sent_day = today
            else:
                # Pas de destinataire / échec : on marque quand même pour ne pas
                # boucler toutes les 30s ; réessai le lendemain.
                self._last_sent_day = today

    @staticmethod
    def _parse_report_time(value: Optional[str]) -> Optional[tuple]:
        """Parse ``"HH:MM"`` en tuple ``(heure, minute)`` ; ``None`` si invalide."""
        if not value:
            return None
        try:
            hh, mm = value.strip().split(":", 1)
            return (int(hh), int(mm))
        except (ValueError, AttributeError):
            logger.warning("report_time invalide : %r", value)
            return None
