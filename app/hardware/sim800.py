"""Driver SIM800 (HAT ITEAD v2.0) — appels & SMS.

Ce module est le **seul** endroit du projet autorisé à parler à l'UART et à
parser les réponses / URC AT du modem. Le reste de l'application consomme
uniquement les méthodes publiques et les callbacks exposés ici.

Modèle de threading :

- ``_reader_loop`` : unique lecteur série. Découpe le flux en lignes, détecte
  le prompt d'envoi SMS (``>``), classe chaque ligne soit comme *réponse de
  commande*, soit comme *URC* (évènement non sollicité).
- ``_worker_loop`` : exécute les callbacks et les actions déclenchées par URC
  (ex : lire puis supprimer un SMS reçu). Cela évite tout blocage / réentrance
  dans le lecteur série.
- ``command`` : sérialisé par un verrou ; écrit la commande puis attend un
  terminateur (``OK`` / ``ERROR`` / …) via une file alimentée par le lecteur.

Réutilisable hors projet : aucune dépendance à Flask, à la base ou aux
services métier.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Terminateurs de réponse d'une commande AT.
_TERMINATORS_OK = ("OK",)
_TERMINATORS_ERR = ("ERROR",)
_ERR_PREFIXES = ("+CME ERROR", "+CMS ERROR")

# Préfixes toujours interprétés comme des URC (évènements non sollicités),
# même pendant l'exécution d'une commande.
_PURE_URC_PREFIXES = (
    "RING",
    "+CLIP:",
    "+CMTI:",
    "NO CARRIER",
    "NORMAL POWER DOWN",
    "RDY",
    "Call Ready",
    "SMS Ready",
    "+CFUN:",
)

_CTRL_Z = b"\x1a"


class SIM800Error(RuntimeError):
    """Erreur renvoyée par le modem (``ERROR`` / ``+CME`` / ``+CMS``) ou timeout."""


@dataclass
class SMSMessage:
    """Représentation décodée d'un SMS lu sur la SIM."""

    index: Optional[int]
    status: str
    number: str
    timestamp: Optional[datetime]
    text: str


class SIM800:
    """Driver série du module SIM800.

    Callbacks exposés (assignables directement) :

    - ``on_ring()`` — un ``RING`` a été reçu.
    - ``on_clip(number: str)`` — numéro de l'appelant (brut).
    - ``on_sms(number, text, timestamp, message_id)`` — SMS reçu et lu.
    - ``on_network(registered: bool)`` — changement d'état réseau (URC CREG).
    - ``on_no_carrier()`` — fin / échec d'appel.
    """

    def __init__(
        self,
        port: str = "/dev/serial0",
        baudrate: int = 115200,
        read_timeout: float = 0.2,
        default_command_timeout: float = 5.0,
        serial_factory: Optional[Callable[..., object]] = None,
    ) -> None:
        """Initialise le driver (ne se connecte pas encore).

        Args:
            port: périphérique série.
            baudrate: débit.
            read_timeout: timeout de lecture série (boucle réactive).
            default_command_timeout: timeout par défaut d'une commande AT.
            serial_factory: fabrique de port série injectable (tests).
        """
        self._port = port
        self._baudrate = baudrate
        self._read_timeout = read_timeout
        self._default_timeout = default_command_timeout
        self._serial_factory = serial_factory

        self._serial: Optional[object] = None
        self._running = False

        self._reader_thread: Optional[threading.Thread] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        # Sérialisation des commandes AT.
        self._cmd_lock = threading.Lock()
        self._command_active = False
        self._response_queue: "queue.Queue[str]" = queue.Queue()

        # Prompt d'envoi SMS ('>').
        self._prompt_event = threading.Event()
        self._awaiting_prompt = False

        # Callbacks (assignés par le service GSM).
        self.on_ring: Optional[Callable[[], None]] = None
        self.on_clip: Optional[Callable[[str], None]] = None
        self.on_sms: Optional[
            Callable[[str, str, Optional[datetime], Optional[str]], None]
        ] = None
        self.on_network: Optional[Callable[[bool], None]] = None
        self.on_no_carrier: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------ #
    # Connexion / cycle de vie
    # ------------------------------------------------------------------ #
    def _open_serial(self) -> object:
        if self._serial_factory is not None:
            return self._serial_factory(
                self._port, self._baudrate, timeout=self._read_timeout
            )
        import serial  # import tardif : dépendance optionnelle en dev

        return serial.Serial(self._port, self._baudrate, timeout=self._read_timeout)

    def connect(self) -> None:
        """Ouvre le port série, démarre les threads et initialise le modem."""
        if self._running:
            return
        logger.info("SIM800 : connexion sur %s @ %d bauds", self._port, self._baudrate)
        self._serial = self._open_serial()
        self._running = True

        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="sim800-worker", daemon=True
        )
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="sim800-reader", daemon=True
        )
        self._worker_thread.start()
        self._reader_thread.start()

        self._initialize_modem()

    def _initialize_modem(self) -> None:
        """Configuration de base du modem (best effort)."""
        # Laisse le temps au modem de démarrer si nécessaire.
        for cmd in (
            "AT",           # ping
            "ATE0",         # coupe l'écho
            "AT+CMEE=1",    # erreurs numériques détaillées
            "AT+CLIP=1",    # présentation du numéro appelant
            "AT+CMGF=1",    # mode texte SMS
            'AT+CNMI=2,1,0,0,0',  # notification URC de nouveau SMS (+CMTI)
        ):
            try:
                self.command(cmd, timeout=self._default_timeout)
            except SIM800Error as exc:
                logger.warning("SIM800 init : '%s' a échoué (%s)", cmd, exc)

    def is_healthy(self) -> bool:
        """``True`` si le driver tourne et que ses deux threads sont vivants.

        Sert de garde-fou complémentaire aux sondes AT : un thread mort (crash
        Python non prévu) ne provoque pas forcément un timeout de ``command``,
        donc on vérifie aussi explicitement l'état des threads.
        """
        if not self._running:
            return False
        reader_ok = self._reader_thread is not None and self._reader_thread.is_alive()
        worker_ok = self._worker_thread is not None and self._worker_thread.is_alive()
        return reader_ok and worker_ok

    def disconnect(self) -> None:
        """Arrête les threads et ferme le port série."""
        self._running = False
        # Débloque le worker.
        self._worker_queue.put(lambda: None)
        for thread in (self._reader_thread, self._worker_thread):
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
        if self._serial is not None:
            try:
                self._serial.close()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - best effort
                logger.exception("Erreur à la fermeture du port série")
        self._serial = None
        logger.info("SIM800 : déconnecté")

    # ------------------------------------------------------------------ #
    # Boucle de lecture série
    # ------------------------------------------------------------------ #
    def _reader_loop(self) -> None:
        buffer = b""
        while self._running:
            try:
                chunk = self._serial.read(64)  # type: ignore[union-attr]
            except Exception:  # pragma: no cover - dépend du matériel
                logger.exception("SIM800 : erreur de lecture série")
                time.sleep(0.5)
                continue

            if not chunk:
                continue
            buffer += chunk

            # Détection du prompt d'envoi SMS ('>').
            if self._awaiting_prompt and b">" in buffer:
                self._prompt_event.set()
                buffer = buffer.split(b">", 1)[1]

            # Découpage en lignes.
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                line = raw_line.decode("utf-8", errors="replace").strip("\r ")
                if line:
                    self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        """Classe une ligne : URC pur, réponse de commande, ou URC réseau."""
        logger.debug("SIM800 <- %s", line)

        if self._is_pure_urc(line):
            self._dispatch_urc(line)
            return

        # +CREG hors commande = URC réseau ; pendant une commande = réponse.
        if line.startswith("+CREG:") and not self._command_active:
            self._dispatch_urc(line)
            return

        if self._command_active:
            self._response_queue.put(line)
        else:
            # Ligne non sollicitée non reconnue : on la journalise seulement.
            logger.debug("SIM800 : ligne non sollicitée ignorée : %s", line)

    @staticmethod
    def _is_pure_urc(line: str) -> bool:
        return any(line.startswith(prefix) for prefix in _PURE_URC_PREFIXES)

    # ------------------------------------------------------------------ #
    # Dispatch des URC
    # ------------------------------------------------------------------ #
    def _dispatch_urc(self, line: str) -> None:
        """Route un URC vers le worker (jamais dans le thread lecteur)."""
        if line.startswith("RING"):
            self._worker_queue.put(lambda: self._safe_call(self.on_ring))
        elif line.startswith("+CLIP:"):
            number = self._parse_clip(line)
            if number is not None:
                self._worker_queue.put(
                    lambda n=number: self._safe_call(self.on_clip, n)
                )
        elif line.startswith("+CMTI:"):
            index = self._parse_cmti(line)
            if index is not None:
                self._worker_queue.put(lambda i=index: self._process_incoming_sms(i))
        elif line.startswith("NO CARRIER"):
            self._worker_queue.put(lambda: self._safe_call(self.on_no_carrier))
        elif line.startswith("+CREG:"):
            registered = self._parse_creg_urc(line)
            self._worker_queue.put(
                lambda r=registered: self._safe_call(self.on_network, r)
            )
        # Les autres URC (RDY, SMS Ready, …) sont purement informatifs.

    def _worker_loop(self) -> None:
        while self._running:
            try:
                task = self._worker_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                task()
            except Exception:  # pragma: no cover - ne doit jamais tuer le worker
                logger.exception("SIM800 : erreur dans une tâche worker")

    @staticmethod
    def _safe_call(callback: Optional[Callable], *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  # pragma: no cover
            logger.exception("SIM800 : callback %r a levé une exception", callback)

    def _process_incoming_sms(self, index: int) -> None:
        """Lit le SMS ``index``, notifie ``on_sms`` puis le supprime."""
        try:
            message = self.read_sms(index)
        except SIM800Error:
            logger.exception("SIM800 : lecture du SMS %s impossible", index)
            return
        if message is None:
            logger.warning("SIM800 : SMS %s introuvable", index)
            return

        self._safe_call(
            self.on_sms,
            message.number,
            message.text,
            message.timestamp,
            str(message.index) if message.index is not None else None,
        )
        # Purge la mémoire SIM pour éviter la saturation.
        try:
            self.delete_sms(index)
        except SIM800Error:
            logger.warning("SIM800 : suppression du SMS %s impossible", index)

    # ------------------------------------------------------------------ #
    # Exécution des commandes AT
    # ------------------------------------------------------------------ #
    def send(self, data: bytes) -> None:
        """Écrit des octets bruts sur le port série."""
        if self._serial is None:
            raise SIM800Error("Port série non connecté")
        self._serial.write(data)  # type: ignore[union-attr]

    def _write_line(self, cmd: str) -> None:
        logger.debug("SIM800 -> %s", cmd)
        self.send((cmd + "\r\n").encode("utf-8"))

    def command(self, cmd: str, timeout: Optional[float] = None) -> List[str]:
        """Envoie une commande AT et retourne les lignes de réponse.

        Args:
            cmd: commande complète (ex : ``"AT+CSQ"``).
            timeout: délai max d'attente du terminateur.

        Returns:
            Les lignes intermédiaires (hors ``OK``), échos exclus.

        Raises:
            SIM800Error: si le modem répond une erreur ou en cas de timeout.
        """
        with self._cmd_lock:
            return self._command_locked(cmd, timeout)

    def _command_locked(self, cmd: str, timeout: Optional[float]) -> List[str]:
        self._drain_response_queue()
        self._command_active = True
        try:
            self._write_line(cmd)
            return self._await_response(cmd, timeout or self._default_timeout)
        finally:
            self._command_active = False

    def _await_response(self, echoed_cmd: str, timeout: float) -> List[str]:
        deadline = time.monotonic() + timeout
        lines: List[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SIM800Error(f"Timeout en attente de réponse à '{echoed_cmd}'")
            try:
                line = self._response_queue.get(timeout=remaining)
            except queue.Empty:
                raise SIM800Error(f"Timeout en attente de réponse à '{echoed_cmd}'")

            if line == echoed_cmd:  # écho éventuel
                continue
            if line in _TERMINATORS_OK:
                return lines
            if line in _TERMINATORS_ERR or line.startswith(_ERR_PREFIXES):
                raise SIM800Error(f"Modem a répondu '{line}' à '{echoed_cmd}'")
            lines.append(line)

    def _drain_response_queue(self) -> None:
        while True:
            try:
                self._response_queue.get_nowait()
            except queue.Empty:
                return

    # ------------------------------------------------------------------ #
    # Informations modem
    # ------------------------------------------------------------------ #
    def get_signal(self, timeout: Optional[float] = None) -> int:
        """Retourne le RSSI (``+CSQ``), 0-31, ou 99 si inconnu."""
        for line in self.command("AT+CSQ", timeout=timeout):
            match = re.search(r"\+CSQ:\s*(\d+),", line)
            if match:
                return int(match.group(1))
        return 99

    def get_operator(self, timeout: Optional[float] = None) -> str:
        """Retourne le nom de l'opérateur (``+COPS?``) ou une chaîne vide."""
        for line in self.command("AT+COPS?", timeout=timeout):
            match = re.search(r'\+COPS:\s*\d+,\d+,"([^"]*)"', line)
            if match:
                return match.group(1)
        return ""

    def get_imei(self, timeout: Optional[float] = None) -> str:
        """Retourne l'IMEI du modem (``AT+GSN``)."""
        for line in self.command("AT+GSN", timeout=timeout):
            if line.isdigit():
                return line
        return ""

    def get_iccid(self, timeout: Optional[float] = None) -> str:
        """Retourne l'ICCID de la SIM (``AT+CCID``)."""
        for line in self.command("AT+CCID", timeout=timeout):
            digits = re.sub(r"\D", "", line)
            if len(digits) >= 18:
                return digits
        return ""

    def network_registered(self, timeout: Optional[float] = None) -> bool:
        """Indique si le modem est enregistré sur le réseau (``+CREG?``)."""
        for line in self.command("AT+CREG?", timeout=timeout):
            match = re.search(r"\+CREG:\s*\d+,\s*(\d+)", line)
            if match:
                return match.group(1) in ("1", "5")
        return False

    def sim_ready(self, timeout: Optional[float] = None) -> bool:
        """Indique si la SIM est prête (``+CPIN: READY``)."""
        try:
            lines = self.command("AT+CPIN?", timeout=timeout)
        except SIM800Error:
            return False
        return any("READY" in line for line in lines)

    # ------------------------------------------------------------------ #
    # Appels
    # ------------------------------------------------------------------ #
    def answer(self) -> None:
        """Décroche l'appel entrant (``ATA``)."""
        self.command("ATA")

    def hangup(self) -> None:
        """Raccroche l'appel en cours (``ATH``)."""
        self.command("ATH")

    def call(self, number: str) -> None:
        """Émet un appel vers ``number`` (``ATD…;``)."""
        self.command(f"ATD{number};")

    # ------------------------------------------------------------------ #
    # SMS
    # ------------------------------------------------------------------ #
    def send_sms(self, number: str, text: str, timeout: float = 20.0) -> None:
        """Envoie un SMS en mode texte.

        Args:
            number: numéro destinataire.
            text: contenu du message.
            timeout: délai max d'attente du ``+CMGS`` / ``OK``.

        Raises:
            SIM800Error: en cas d'échec (pas de prompt, erreur modem, timeout).
        """
        with self._cmd_lock:
            self._command_locked("AT+CMGF=1", self._default_timeout)

            self._drain_response_queue()
            self._prompt_event.clear()
            self._awaiting_prompt = True
            self._command_active = True
            try:
                self._write_line(f'AT+CMGS="{number}"')
                if not self._prompt_event.wait(timeout=self._default_timeout):
                    raise SIM800Error("SIM800 : prompt '>' non reçu pour l'envoi SMS")
                # Corps du message suivi de Ctrl-Z.
                self.send(text.encode("utf-8", errors="replace") + _CTRL_Z)
                self._await_response("AT+CMGS", timeout)
            finally:
                self._awaiting_prompt = False
                self._command_active = False
        logger.info("SIM800 : SMS envoyé à %s", number)

    def _ensure_text_mode(self) -> None:
        """Réaffirme le mode texte SMS (``AT+CMGF=1``).

        Le modem peut repasser en mode PDU (défaut) après un reset ou une
        perte de configuration : dans ce cas ``+CMGR`` renvoie une trame PDU
        que le parseur texte ne sait pas décoder (numéro vide → SMS rejeté).
        On force donc le mode texte juste avant chaque lecture.
        """
        try:
            self.command("AT+CMGF=1")
        except SIM800Error:
            logger.warning("SIM800 : impossible de forcer le mode texte SMS (CMGF=1)")

    def read_sms(self, index: int) -> Optional[SMSMessage]:
        """Lit le SMS à l'``index`` donné (``+CMGR``). ``None`` si absent."""
        self._ensure_text_mode()
        lines = self.command(f"AT+CMGR={index}")
        header_idx = next(
            (i for i, ln in enumerate(lines) if ln.startswith("+CMGR:")), None
        )
        if header_idx is None:
            if lines:
                logger.warning(
                    "SIM800 : réponse +CMGR inattendue pour le SMS %s "
                    "(mode PDU ?) : %r",
                    index,
                    lines,
                )
            return None
        status, number, timestamp = self._parse_cmgr_header(lines[header_idx])
        body = "\n".join(lines[header_idx + 1:]).strip()
        return SMSMessage(
            index=index,
            status=status,
            number=number,
            timestamp=timestamp,
            text=body,
        )

    def delete_sms(self, index: int) -> None:
        """Supprime le SMS à l'``index`` donné (``+CMGD``)."""
        self.command(f"AT+CMGD={index}")

    def list_sms(self, status: str = "ALL") -> List[SMSMessage]:
        """Liste les SMS stockés (``+CMGL``).

        Args:
            status: filtre (``"ALL"``, ``"REC UNREAD"``, …).

        Returns:
            La liste des SMS décodés.
        """
        self.command("AT+CMGF=1")
        lines = self.command(f'AT+CMGL="{status}"', timeout=self._default_timeout)
        messages: List[SMSMessage] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("+CMGL:"):
                idx, stat, number, timestamp = self._parse_cmgl_header(line)
                body_lines: List[str] = []
                i += 1
                while i < len(lines) and not lines[i].startswith("+CMGL:"):
                    body_lines.append(lines[i])
                    i += 1
                messages.append(
                    SMSMessage(
                        index=idx,
                        status=stat,
                        number=number,
                        timestamp=timestamp,
                        text="\n".join(body_lines).strip(),
                    )
                )
            else:
                i += 1
        return messages

    # ------------------------------------------------------------------ #
    # Parsing AT (privé)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_clip(line: str) -> Optional[str]:
        match = re.search(r'\+CLIP:\s*"([^"]*)"', line)
        return match.group(1) if match else None

    @staticmethod
    def _parse_cmti(line: str) -> Optional[int]:
        match = re.search(r'\+CMTI:\s*"[^"]*",\s*(\d+)', line)
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_creg_urc(line: str) -> bool:
        match = re.search(r"\+CREG:\s*(\d+)", line)
        return bool(match) and match.group(1) in ("1", "5")

    @classmethod
    def _parse_cmgr_header(cls, line: str):
        match = re.search(
            r'\+CMGR:\s*"([^"]*)","([^"]*)",(?:"[^"]*")?,"([^"]*)"', line
        )
        if not match:
            return "", "", None
        status, number, ts_raw = match.group(1), match.group(2), match.group(3)
        return status, number, cls._parse_sms_timestamp(ts_raw)

    @classmethod
    def _parse_cmgl_header(cls, line: str):
        match = re.search(
            r'\+CMGL:\s*(\d+),"([^"]*)","([^"]*)",(?:"[^"]*")?,"([^"]*)"', line
        )
        if not match:
            return None, "", "", None
        idx = int(match.group(1))
        status, number, ts_raw = match.group(2), match.group(3), match.group(4)
        return idx, status, number, cls._parse_sms_timestamp(ts_raw)

    @staticmethod
    def _parse_sms_timestamp(raw: Optional[str]) -> Optional[datetime]:
        """Parse un horodatage SMS ``yy/MM/dd,HH:mm:ss±zz``."""
        if not raw:
            return None
        # Retire le fuseau (± suivi de chiffres) que datetime ne sait pas lire.
        cleaned = re.sub(r"[+\-]\d{1,2}$", "", raw.strip())
        try:
            return datetime.strptime(cleaned, "%y/%m/%d,%H:%M:%S")
        except ValueError:
            return None