"""Faux port série pour le développement sans matériel.

Répond ``OK`` aux commandes AT basiques afin que le driver SIM800 démarre sans
erreur hors Raspberry Pi. Ce n'est pas un simulateur complet : aucun URC
(RING, +CMTI…) n'est généré.
"""

from __future__ import annotations

import logging
import queue
from typing import Optional

logger = logging.getLogger(__name__)


class FakeSerial:
    """Implémente l'interface minimale attendue par ``SIM800`` (read/write/close)."""

    def __init__(self, port: str = "fake", baudrate: int = 115200, timeout: Optional[float] = 0.2):
        self._port = port
        self._timeout = timeout if timeout is not None else 0.2
        self._rx: "queue.Queue[int]" = queue.Queue()
        logger.info("FakeSerial actif sur %s (mode dev, sans matériel)", port)

    # -- écriture : on renvoie 'OK' à toute ligne de commande -------------- #
    def write(self, data: bytes) -> int:
        text = data.decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if line and line.upper().startswith("AT") or line.upper() in {"ATA", "ATH"}:
                self._enqueue("OK")
        return len(data)

    # -- lecture bloquante bornée par le timeout --------------------------- #
    def read(self, size: int = 1) -> bytes:
        out = bytearray()
        try:
            out.append(self._rx.get(timeout=self._timeout))
        except queue.Empty:
            return bytes(out)
        while len(out) < size:
            try:
                out.append(self._rx.get_nowait())
            except queue.Empty:
                break
        return bytes(out)

    def close(self) -> None:
        logger.debug("FakeSerial fermé (%s)", self._port)

    # -- interne ----------------------------------------------------------- #
    def _enqueue(self, line: str) -> None:
        for byte in (line + "\r\n").encode("utf-8"):
            self._rx.put(byte)
