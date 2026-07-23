"""CommandService : routeur de commandes texte, indépendant du canal.

Reçoit un texte de commande déjà associé à un numéro whitelisté (la
vérification whitelist reste du ressort de l'appelant : ``GSMService.on_sms``
aujourd'hui, un futur ``TelegramService`` demain) et retourne un résultat
générique (relais déclenché ou non, texte de réponse éventuel).

Volontairement sans dépendance à Flask, à SIM800 ou à un bot Telegram : ce
service ne *sait pas* comment le texte est arrivé ni comment la réponse sera
envoyée, il se contente d'interpréter la commande. Cela permet de brancher
plusieurs canaux (SMS, Telegram, futur…) sur la même logique métier, sans
dupliquer whitelist/permissions/journalisation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from app.models import RELAY_SOURCE_SMS, Phone
from app.services.phone_service import PhoneService
from app.services.relay_service import RelayService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Résultat de l'interprétation d'une commande."""

    recognized: bool  # le premier mot correspond à une commande connue
    command: Optional[str] = None  # nom normalisé ("OUVRE", "STOP", ...)
    relay_triggered: bool = False
    reply_text: Optional[str] = None
    # ``True`` si la commande était reconnue mais rejetée (PIN invalide,
    # réservée aux admins, argument manquant...) — utile pour la journalisation
    # (distingue "commande inconnue" de "commande refusée").
    rejected: bool = False


class CommandService:
    """Interprète une commande texte whitelistée et agit en conséquence.

    Args:
        phone_service: whitelist (lookup + ajout de numéros via ``AJOUTE``).
        relay_service: déclenchement du relais (commande ``OUVRE``).
        settings_service: configuration (mots-clés de commande, PIN, admins).
        status_provider: renvoie un instantané du statut GSM (voir
            ``GSMService.get_status``) — utilisé par ``STATUT``.
        report_trigger: déclenche l'envoi immédiat du rapport quotidien
            (voir ``GSMService.send_daily_report_now``) — utilisé par
            ``RAPPORT``. ``None`` si aucun canal de rapport n'est câblé.
    """

    def __init__(
        self,
        phone_service: PhoneService,
        relay_service: RelayService,
        settings_service: SettingsService,
        status_provider: Callable[[], Dict[str, object]],
        report_trigger: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._phones = phone_service
        self._relay = relay_service
        self._settings = settings_service
        self._status_provider = status_provider
        self._report_trigger = report_trigger

    # ------------------------------------------------------------------ #
    # Point d'entrée
    # ------------------------------------------------------------------ #
    def dispatch(
        self, number: str, phone: Optional[Phone], text: str, source: str = RELAY_SOURCE_SMS
    ) -> CommandResult:
        """Interprète ``text`` (déjà whitelisté) et retourne le résultat.

        Args:
            number: numéro normalisé de l'émetteur.
            phone: enregistrement ``Phone`` correspondant (whitelisté).
            text: contenu brut de la commande.
            source: ``"sms"`` (ou futur ``"telegram"``) — transmis au relais
                pour la journalisation (``RelayEvent.source``).
        """
        tokens = (text or "").strip().split()
        if not tokens:
            return CommandResult(recognized=False)

        keyword = tokens[0].strip().upper()
        args = tokens[1:]

        table = {
            self._setting_upper("sms_command_open", "OUVRE"): self._cmd_open,
            self._setting_upper("sms_command_stop", "STOP"): self._cmd_stop,
            self._setting_upper("sms_command_start", "START"): self._cmd_start,
            self._setting_upper("sms_command_status", "STATUT"): self._cmd_status,
            self._setting_upper("sms_command_add", "AJOUTE"): self._cmd_add,
            self._setting_upper("sms_command_report", "RAPPORT"): self._cmd_report,
        }

        handler = table.get(keyword)
        if handler is None:
            return CommandResult(recognized=False)

        return handler(number=number, phone=phone, args=args, source=source)

    # ------------------------------------------------------------------ #
    # Commandes
    # ------------------------------------------------------------------ #
    def _cmd_open(
        self, number: str, phone: Optional[Phone], args: List[str], source: str
    ) -> CommandResult:
        pin = (self._settings.get("sms_command_pin", "") or "").strip()
        if pin:
            provided = args[0] if args else ""
            if provided != pin:
                logger.info("Commande OUVRE : PIN invalide de %s.", number)
                return CommandResult(recognized=True, command="OUVRE", rejected=True)

        try:
            self._relay.trigger(
                source=source,
                phone_id=phone.id if phone else None,
                metadata={"number": number, "command": "OUVRE"},
            )
            triggered = True
        except Exception:  # pragma: no cover - défensif
            logger.exception("Erreur lors du déclenchement du relais (commande OUVRE)")
            triggered = False

        reply = None
        if triggered and self._settings.get_bool("sms_reply_enabled", default=False):
            reply = self._settings.get("sms_reply_text", "Garage ouvert") or "Garage ouvert"

        return CommandResult(
            recognized=True, command="OUVRE", relay_triggered=triggered, reply_text=reply
        )

    def _cmd_stop(
        self, number: str, phone: Optional[Phone], args: List[str], source: str
    ) -> CommandResult:
        if not self._is_admin(number):
            logger.info("Commande STOP refusée (non admin) : %s", number)
            return CommandResult(recognized=True, command="STOP", rejected=True)
        self._settings.set("sms_enabled", False)
        logger.warning("Commandes SMS désactivées par %s (commande STOP).", number)
        return CommandResult(
            recognized=True,
            command="STOP",
            reply_text="Commandes SMS désactivées. Renvoyez START pour réactiver.",
        )

    def _cmd_start(
        self, number: str, phone: Optional[Phone], args: List[str], source: str
    ) -> CommandResult:
        if not self._is_admin(number):
            logger.info("Commande START refusée (non admin) : %s", number)
            return CommandResult(recognized=True, command="START", rejected=True)
        self._settings.set("sms_enabled", True)
        logger.info("Commandes SMS réactivées par %s (commande START).", number)
        return CommandResult(
            recognized=True, command="START", reply_text="Commandes SMS réactivées."
        )

    def _cmd_status(
        self, number: str, phone: Optional[Phone], args: List[str], source: str
    ) -> CommandResult:
        if not self._is_admin(number):
            return CommandResult(recognized=True, command="STATUT", rejected=True)
        status = self._status_provider() or {}
        reachable = status.get("modem_reachable")
        signal = status.get("signal")
        registered = status.get("network_registered")
        watchdog = status.get("watchdog") or {}
        sms_state = "ON" if self._settings.get_bool("sms_enabled", default=True) else "OFF"

        parts = [
            f"Modem: {'OK' if reachable else 'HS'}",
            f"Reseau: {'connecte' if registered else 'non connecte'}",
        ]
        if signal is not None:
            parts.append(f"Signal: {signal}")
        parts.append(f"SMS: {sms_state}")
        failures = watchdog.get("consecutive_failures")
        if failures:
            parts.append(f"Echecs watchdog: {failures}")

        return CommandResult(
            recognized=True, command="STATUT", reply_text=" | ".join(parts)
        )

    def _cmd_add(
        self, number: str, phone: Optional[Phone], args: List[str], source: str
    ) -> CommandResult:
        if not self._is_admin(number):
            logger.info("Commande AJOUTE refusée (non admin) : %s", number)
            return CommandResult(recognized=True, command="AJOUTE", rejected=True)

        if not args:
            return CommandResult(
                recognized=True,
                command="AJOUTE",
                rejected=True,
                reply_text="Usage : AJOUTE <numero> [nom]",
            )

        new_number = args[0]
        new_name = " ".join(args[1:]) if len(args) > 1 else None
        try:
            added = self._phones.add_phone(new_number, name=new_name, enabled=True)
        except ValueError as exc:
            logger.info("Commande AJOUTE échouée pour %s : %s", new_number, exc)
            return CommandResult(
                recognized=True, command="AJOUTE", rejected=True, reply_text=str(exc)
            )

        logger.warning(
            "Numéro %s ajouté à la whitelist par %s (commande AJOUTE).", added.number, number
        )
        return CommandResult(
            recognized=True,
            command="AJOUTE",
            reply_text=f"Numero {added.number} ajoute.",
        )

    def _cmd_report(
        self, number: str, phone: Optional[Phone], args: List[str], source: str
    ) -> CommandResult:
        if not self._is_admin(number):
            return CommandResult(recognized=True, command="RAPPORT", rejected=True)
        if self._report_trigger is None:
            return CommandResult(
                recognized=True,
                command="RAPPORT",
                rejected=True,
                reply_text="Rapport indisponible.",
            )
        sent = self._report_trigger()
        return CommandResult(
            recognized=True,
            command="RAPPORT",
            reply_text="Rapport envoye." if sent else "Echec envoi rapport.",
        )

    # ------------------------------------------------------------------ #
    # Aides
    # ------------------------------------------------------------------ #
    def _setting_upper(self, key: str, default: str) -> str:
        return (self._settings.get(key, default) or default).strip().upper()

    def _is_admin(self, number: str) -> bool:
        """Vrai si ``number`` est autorisé pour les commandes sensibles.

        Si ``sms_admin_numbers`` (JSON, ``Setting``) est vide, TOUT numéro
        whitelisté est considéré admin (comportement historique, aucune
        configuration requise). Sinon, seuls les numéros listés le sont —
        permet de restreindre STOP/START/AJOUTE/STATUT/RAPPORT à un
        sous-ensemble de la whitelist (ex. le propriétaire uniquement).
        """
        admins = self._settings.get_list("sms_admin_numbers")
        if not admins:
            return True
        return number in admins