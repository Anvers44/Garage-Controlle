"""Notification systemd (``sd_notify``) sans dépendance externe.

Permet d'utiliser le *watchdog* systemd (``WatchdogSec=`` dans l'unité) :
si le process ne notifie plus ``WATCHDOG=1`` à temps, systemd le tue et le
redémarre (``Restart=on-failure``). Contrairement à ``Restart=on-failure``
seul, ceci couvre le cas d'un process qui reste en vie mais **bloqué**
(threads morts, boucle figée), pas seulement un crash.

Implémentation minimale : écrit directement sur le socket Unix indiqué par
``$NOTIFY_SOCKET`` (fourni par systemd pour les unités ``Type=notify``).
Ne fait rien (no-op silencieux) si la variable n'est pas définie — utile en
dev ou hors systemd, sans avoir à installer ``python-systemd``.
"""

from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger(__name__)


def _notify_socket_path() -> str | None:
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return None
    # systemd peut préfixer par '@' pour un socket abstrait (Linux).
    if path.startswith("@"):
        path = "\0" + path[1:]
    return path


def sd_notify(state: str) -> bool:
    """Envoie une notification à systemd (ex : ``\"READY=1\"``, ``\"WATCHDOG=1\"``).

    Returns:
        ``True`` si le message a été envoyé (ou si aucun watchdog systemd
        n'est configuré : rien à faire, ce n'est pas une erreur), ``False``
        si l'envoi a échoué alors qu'un socket était configuré.
    """
    path = _notify_socket_path()
    if not path:
        return True  # Pas sous systemd (dev, GARAGE_FAKE_SERIAL, etc.) : no-op.

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(path)
            sock.sendall(state.encode("utf-8"))
        return True
    except OSError:
        logger.warning("sd_notify(%r) : échec d'envoi sur %s", state, path)
        return False


def watchdog_enabled() -> bool:
    """``True`` si systemd attend des pings watchdog (``WatchdogSec=`` actif)."""
    return bool(os.environ.get("WATCHDOG_USEC")) and bool(_notify_socket_path())