"""GSMService : cœur métier orchestrant appels & SMS.

Ce service branche les callbacks du driver SIM800 et implémente les flux
décrits dans docs/spec-sms.md :

- appel whitelist  → réponse ~2s → raccroché → relais → journalisation ;
- SMS whitelist    → commande valide → relais → journalisation (+ réponse) ;
- rapport quotidien → délégué à ``ReportingScheduler``.

Il ne parle jamais directement à Flask/SocketIO et ne parse aucune réponse AT
(tout le parsing vit dans le driver SIM800).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

from app.hardware.sim800 import SIM800, SIM800Error
from app.models import RELAY_SOURCE_CALL, RELAY_SOURCE_SMS
from app.services.history_service import HistoryService
from app.services.phone_service import PhoneService
from app.services.relay_service import RelayService
from app.services.reporting_service import ReportingScheduler, ReportingService
from app.services.settings_service import SettingsService
from app.utils.phone_numbers import normalize_number

logger = logging.getLogger(__name__)


class GSMService:
    """Service GSM indépendant (tourne hors Flask)."""

    def __init__(
        self,
        sim800: SIM800,
        phone_service: PhoneService,
        relay_service: RelayService,
        history_service: HistoryService,
        settings_service: SettingsService,
        reporting_service: Optional[ReportingService] = None,
    ) -> None:
        self._sim = sim800
        self._phones = phone_service
        self._relay = relay_service
        self._history = history_service
        self._settings = settings_service

        self._reporting = reporting_service or ReportingService(
            history_service, settings_service, sim800
        )
        self._scheduler = ReportingScheduler(self._reporting, settings_service)

        # Rate limiting SMS : dernier déclenchement (monotone) par numéro.
        self._last_sms_open: Dict[str, float] = {}
        self._rate_lock = threading.Lock()

        # Cache du statut GSM (les requêtes AT sont coûteuses et ne doivent
        # jamais bloquer un thread de requête web : elles sont rafraîchies
        # en tâche de fond par ``_status_refresh_loop``).
        self._status_cache: Dict[str, object] = {
            "signal": None,
            "operator": None,
            "imei": None,
            "iccid": None,
            "sim_ready": None,
            "network_registered": None,
            "modem_reachable": None,
        }
        self._status_ts: float = 0.0
        self._status_lock = threading.Lock()
        self._status_refresh_interval = 20.0  # secondes entre 2 cycles de sondes
        self._status_probe_timeout = 1.5  # timeout court : on veut échouer vite
        self._status_thread: Optional[threading.Thread] = None
        self._status_stop_event = threading.Event()

        self._started = False

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Initialise les paramètres, branche les callbacks et démarre tout."""
        if self._started:
            return
        self._settings.ensure_defaults()

        self._sim.on_clip = self.on_clip
        self._sim.on_sms = self.on_sms
        self._sim.on_no_carrier = self._on_no_carrier

        self._sim.connect()
        self._scheduler.start()

        self._status_stop_event.clear()
        self._status_thread = threading.Thread(
            target=self._status_refresh_loop, name="gsm-status", daemon=True
        )
        self._status_thread.start()

        self._started = True
        logger.info("GSMService démarré.")

    def stop(self) -> None:
        """Arrête le scheduler, le rafraîchissement de statut et déconnecte le modem."""
        self._status_stop_event.set()
        if self._status_thread is not None:
            self._status_thread.join(timeout=5.0)
            self._status_thread = None
        self._scheduler.stop()
        self._sim.disconnect()
        self._started = False
        logger.info("GSMService arrêté.")

    # ------------------------------------------------------------------ #
    # Rafraîchissement du statut GSM (thread de fond)
    # ------------------------------------------------------------------ #
    def _status_refresh_loop(self) -> None:
        """Sonde le modem périodiquement et met à jour le cache.

        Tourne dans son propre thread : les commandes AT (jusqu'à 6, avec un
        timeout court chacune) ne bloquent donc jamais un thread de requête
        Flask. Si le modem est injoignable (HAT éteint), chaque sonde échoue
        vite (``_status_probe_timeout``) au lieu de faire attendre l'appelant
        jusqu'à 5 s par commande.
        """
        while not self._status_stop_event.is_set():
            self._refresh_status_cache()
            self._status_stop_event.wait(self._status_refresh_interval)

    def _refresh_status_cache(self) -> None:
        timeout = self._status_probe_timeout
        # Sonde rapide unique : si le modem ne répond même pas à un simple
        # "AT", inutile d'attendre le timeout sur les 6 sondes suivantes.
        try:
            self._sim.command("AT", timeout=timeout)
            reachable = True
        except SIM800Error:
            reachable = False

        if not reachable:
            with self._status_lock:
                self._status_cache = {
                    "signal": None,
                    "operator": None,
                    "imei": None,
                    "iccid": None,
                    "sim_ready": False,
                    "network_registered": False,
                    "modem_reachable": False,
                }
                self._status_ts = time.monotonic()
            return

        probes = {
            "signal": self._sim.get_signal,
            "operator": self._sim.get_operator,
            "imei": self._sim.get_imei,
            "iccid": self._sim.get_iccid,
            "sim_ready": self._sim.sim_ready,
            "network_registered": self._sim.network_registered,
        }
        status: Dict[str, object] = {"modem_reachable": True}
        for key, probe in probes.items():
            try:
                status[key] = probe(timeout=timeout)
            except Exception:  # pragma: no cover - dépend du modem
                status[key] = None

        with self._status_lock:
            self._status_cache = status
            self._status_ts = time.monotonic()

    # ------------------------------------------------------------------ #
    # Flux APPEL entrant
    # ------------------------------------------------------------------ #
    def on_clip(self, raw_number: str) -> None:
        """Traite un appel entrant identifié (callback driver ``on_clip``)."""
        number = normalize_number(raw_number)
        logger.info("Appel entrant de %s (brut=%s)", number, raw_number)

        phone = self._phones.get_by_number(number)
        authorized = bool(phone and phone.enabled)
        phone_id = phone.id if phone else None

        if not authorized:
            logger.info("Appel refusé (numéro non autorisé) : %s", number)
            # Raccroche immédiatement (dès le premier RING) pour couper l'appel
            # au lieu de le laisser sonner.
            try:
                self._sim.hangup()
            except SIM800Error:
                logger.warning("Impossible de raccrocher l'appel non autorisé de %s", number)
            self._history.record_call(
                phone_number=number,
                authorized=False,
                answered=False,
                relay_triggered=False,
                phone_id=phone_id,
                source="call",
            )
            return

        answer_duration = self._settings.get_float(
            "call_answer_duration_seconds", default=2.0
        )
        relay_triggered = False
        try:
            self._sim.answer()
            time.sleep(max(0.0, answer_duration))
            self._sim.hangup()
        except SIM800Error:
            logger.exception("Erreur SIM800 pendant le décroché/raccroché")

        try:
            self._relay.trigger(
                source=RELAY_SOURCE_CALL,
                phone_id=phone_id,
                metadata={"number": number},
            )
            relay_triggered = True
        except Exception:  # pragma: no cover - défensif
            logger.exception("Erreur lors du déclenchement du relais (appel)")

        self._history.record_call(
            phone_number=number,
            authorized=True,
            answered=True,
            relay_triggered=relay_triggered,
            duration=answer_duration,
            phone_id=phone_id,
            source="call",
        )
        logger.info("Ouverture par appel effectuée pour %s", number)

    def _on_no_carrier(self) -> None:
        logger.debug("NO CARRIER (fin d'appel).")

    # ------------------------------------------------------------------ #
    # Flux SMS entrant
    # ------------------------------------------------------------------ #
    def on_sms(
        self,
        raw_number: str,
        text: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
    ) -> None:
        """Traite un SMS entrant (callback driver ``on_sms``)."""
        if not self._settings.get_bool("sms_enabled", default=True):
            logger.debug("SMS ignoré (fonction SMS désactivée).")
            return

        number = normalize_number(raw_number)
        logger.info("SMS de %s : %r", number, text)

        phone = self._phones.get_by_number(number)
        authorized = bool(phone and phone.enabled)
        phone_id = phone.id if phone else None

        if not authorized:
            logger.info("SMS refusé (numéro non autorisé) : %s", number)
            self._history.record_call(
                phone_number=number,
                authorized=False,
                answered=False,
                relay_triggered=False,
                phone_id=phone_id,
                source="sms",
            )
            return

        is_open_cmd, valid = self._parse_sms_command(text)
        if not (is_open_cmd and valid):
            logger.info("Commande SMS invalide de %s : %r", number, text)
            self._history.record_call(
                phone_number=number,
                authorized=True,
                answered=False,
                relay_triggered=False,
                phone_id=phone_id,
                source="sms",
            )
            return

        # Rate limiting.
        if not self._check_and_update_rate_limit(number):
            logger.info("Commande SMS ignorée (rate limit) : %s", number)
            self._history.record_call(
                phone_number=number,
                authorized=True,
                answered=False,
                relay_triggered=False,
                phone_id=phone_id,
                source="sms",
            )
            return

        relay_triggered = False
        try:
            self._relay.trigger(
                source=RELAY_SOURCE_SMS,
                phone_id=phone_id,
                metadata={"number": number, "message_id": message_id, "command": text},
            )
            relay_triggered = True
        except Exception:  # pragma: no cover - défensif
            logger.exception("Erreur lors du déclenchement du relais (SMS)")

        self._history.record_call(
            phone_number=number,
            authorized=True,
            answered=False,
            relay_triggered=relay_triggered,
            phone_id=phone_id,
            source="sms",
        )

        if relay_triggered and self._settings.get_bool("sms_reply_enabled", default=False):
            reply = self._settings.get("sms_reply_text", "Garage ouvert") or "Garage ouvert"
            self._send_reply(number, reply)

        logger.info("Ouverture par SMS effectuée pour %s", number)

    def _send_reply(self, number: str, text: str, attempts: int = 2) -> bool:
        """Envoie le SMS de confirmation, avec une nouvelle tentative si besoin.

        Juste après la réception d'un SMS, le modem est souvent occupé (stockage
        du message reçu) et le premier envoi peut échouer : on laisse le modem se
        stabiliser puis on réessaie.
        """
        for attempt in range(1, attempts + 1):
            try:
                self._sim.send_sms(number, text)
                return True
            except SIM800Error as exc:
                logger.warning(
                    "Réponse SMS à %s : échec (tentative %d/%d) : %s",
                    number,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts:
                    time.sleep(1.5)
        return False

    # ------------------------------------------------------------------ #
    # Helpers SMS
    # ------------------------------------------------------------------ #
    def _parse_sms_command(self, text: str) -> Tuple[bool, bool]:
        """Analyse le texte du SMS.

        Returns:
            ``(is_open_command, is_valid)`` :
            - ``is_open_command`` : le message correspond bien à la commande
              d'ouverture (indépendamment du PIN).
            - ``is_valid`` : commande reconnue ET PIN correct (si requis).
        """
        command_open = (self._settings.get("sms_command_open", "OUVRE") or "OUVRE").strip().upper()
        pin = (self._settings.get("sms_command_pin", "") or "").strip()

        tokens = (text or "").strip().upper().split()
        if not tokens or tokens[0] != command_open:
            return (False, False)

        if not pin:
            return (True, True)

        provided = tokens[1] if len(tokens) > 1 else ""
        return (True, provided == pin.upper())

    def _check_and_update_rate_limit(self, number: str) -> bool:
        """Retourne ``True`` si l'ouverture est autorisée, et note l'horodatage.

        Empêche plus d'une ouverture par SMS toutes les
        ``min_interval_sms_open_seconds`` secondes pour un même numéro.
        """
        min_interval = self._settings.get_float(
            "min_interval_sms_open_seconds", default=30.0
        )
        now = time.monotonic()
        with self._rate_lock:
            last = self._last_sms_open.get(number)
            if last is not None and (now - last) < min_interval:
                return False
            self._last_sms_open[number] = now
            return True

    # ------------------------------------------------------------------ #
    # Statut GSM (pour le dashboard) & actions modem
    # ------------------------------------------------------------------ #
    def get_status(self, max_age: float = 10.0, force: bool = False) -> Dict[str, object]:
        """Retourne un instantané du statut GSM (signal, opérateur, SIM…).

        Lecture pure du cache maintenu par le thread ``_status_refresh_loop`` :
        n'envoie jamais de commande AT dans le thread appelant, donc n'ajoute
        jamais de latence à une requête web, même si le modem est éteint ou
        injoignable. ``force`` déclenche un rafraîchissement immédiat en
        arrière-plan (non bloquant) pour que le prochain appel voie des
        données fraîches, mais renvoie tout de suite le cache actuel.
        """
        if force:
            threading.Thread(
                target=self._refresh_status_cache, name="gsm-status-force", daemon=True
            ).start()
        with self._status_lock:
            return dict(self._status_cache)

    def reboot_modem(self) -> None:
        """Redémarre le modem (``AT+CFUN=1,1``)."""
        self._sim.command("AT+CFUN=1,1", timeout=10.0)
        with self._status_lock:
            self._status_cache = {}

    def test_communication(self) -> bool:
        """Teste la communication avec le modem (``AT`` → ``OK``)."""
        try:
            self._sim.command("AT")
            return True
        except SIM800Error:
            return False

    # ------------------------------------------------------------------ #
    # Rapport (déclenchement manuel éventuel)
    # ------------------------------------------------------------------ #
    def send_daily_report_now(self) -> bool:
        """Force l'envoi immédiat du rapport du jour (utile pour tests/UI)."""
        return self._reporting.send_daily_report()
