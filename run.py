#!/usr/bin/env python3
"""Point d'entrée du Garage Controller GSM.

Un seul process héberge :

- le **backend GSM** (threads série SIM800, relais, scheduler de rapport) ;
- l'**interface web** Flask (dashboard, whitelist, historique, paramètres),
  qui partage le même ``ServiceContainer`` que le backend.

Les deux partagent le même modem et le même GPIO : ils doivent donc vivre dans
le même process (un seul propriétaire de ``/dev/serial0`` et du relais).

Variables d'environnement utiles :
    GARAGE_FAKE_SERIAL=0        # dev sans matériel (faux port série + GPIO mock)
    GARAGE_WEB_ENABLED=1        # mode backend seul (pas d'interface web)
    GARAGE_WEB_HOST=0.0.0.0
    GARAGE_WEB_PORT=8080
    GARAGE_LOG_LEVEL=DEBUG
    GARAGE_SERIAL_PORT=/dev/serial0
    GARAGE_RELAY_PIN=27
"""

from __future__ import annotations

import logging
import os
import signal
import threading

from app.backend import Backend
from app.config import Config
from app.utils.logging import setup_logging
from app.utils.systemd_notify import sd_notify, watchdog_enabled

logger = logging.getLogger("garage.run")

# Systemd notifie l'intervalle du watchdog (µs) via $WATCHDOG_USEC quand
# ``WatchdogSec=`` est configuré dans l'unité. On envoie le "battement de
# cœur" à la moitié de cet intervalle, comme recommandé par systemd (marge
# de sécurité en cas de gigue).
_WATCHDOG_HEARTBEAT_FALLBACK_SECONDS = 30.0


def _watchdog_heartbeat_loop(backend: Backend, stop_event: threading.Event) -> None:
    """Notifie systemd (``WATCHDOG=1``) tant que le service GSM est sain.

    N'envoie **pas** de notification si ``GSMService.is_healthy()`` renvoie
    ``False`` (reconnexion complète en cours ou échouée) : si ça dure plus
    longtemps que ``WatchdogSec=`` dans l'unité systemd, systemd considère le
    process comme figé et le tue/redémarre (``Restart=on-failure`` s'occupe
    du reste). C'est le filet de sécurité de dernier recours, au-dessus des
    actions correctives internes du ``GSMService``.

    No-op silencieux si l'unité n'est pas ``Type=notify`` avec un
    ``WatchdogSec=`` (dev, ``GARAGE_FAKE_SERIAL``, etc.).
    """
    if not watchdog_enabled():
        return

    try:
        interval = int(os.environ["WATCHDOG_USEC"]) / 1_000_000 / 2
    except (KeyError, ValueError):
        interval = _WATCHDOG_HEARTBEAT_FALLBACK_SECONDS

    logger.info("Watchdog systemd actif (heartbeat toutes les %.1fs).", interval)
    while not stop_event.is_set():
        try:
            gsm_healthy = backend.services is not None and backend.services.gsm.is_healthy()
        except Exception:  # pragma: no cover - défensif
            gsm_healthy = False

        if gsm_healthy:
            sd_notify("WATCHDOG=1")
        else:
            logger.warning(
                "Watchdog systemd : GSM non sain, pas de heartbeat "
                "(le process sera redémarré si ça persiste)."
            )
        stop_event.wait(interval)


def _run_headless(backend: Backend, stop_event: threading.Event) -> None:
    """Boucle backend seul : bloque jusqu'à réception d'un signal d'arrêt."""
    logger.info("Backend opérationnel (mode headless). Ctrl+C pour quitter.")
    stop_event.wait()


def _run_web(backend: Backend, config: Config, stop_event: threading.Event) -> None:
    """Sert l'interface web dans un thread et attend le signal d'arrêt.

    On utilise ``make_server`` (plutôt que ``app.run``) afin de pouvoir arrêter
    proprement le serveur sur SIGTERM (``systemctl stop``) et laisser le backend
    libérer le modem et le GPIO.
    """
    from werkzeug.serving import make_server

    from app.web import create_app

    app = create_app(backend)
    server = make_server(config.web_host, config.web_port, app, threaded=True)
    web_thread = threading.Thread(target=server.serve_forever, name="web", daemon=True)
    web_thread.start()
    logger.info(
        "Interface web sur http://%s:%d (login par défaut: admin/admin)",
        config.web_host,
        config.web_port,
    )

    stop_event.wait()
    logger.info("Arrêt de l'interface web…")
    server.shutdown()
    web_thread.join(timeout=5.0)


def main() -> int:
    config = Config.from_env()
    setup_logging(
        log_dir=config.log_dir,
        level=config.log_level,
        max_bytes=config.log_max_bytes,
        backup_count=config.log_backup_count,
    )

    logger.info("=== Démarrage Garage Controller GSM ===")
    backend = Backend(config)
    stop_event = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info("Signal %s reçu : arrêt en cours…", signal.Signals(signum).name)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        backend.start()
    except Exception:
        logger.exception("Échec du démarrage du backend")
        backend.stop()
        return 1

    # Signale à systemd que le démarrage est terminé (no-op si Type != notify).
    sd_notify("READY=1")
    watchdog_thread = threading.Thread(
        target=_watchdog_heartbeat_loop,
        args=(backend, stop_event),
        name="systemd-watchdog",
        daemon=True,
    )
    watchdog_thread.start()

    try:
        if config.web_enabled:
            _run_web(backend, config, stop_event)
        else:
            _run_headless(backend, stop_event)
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        sd_notify("STOPPING=1")
        backend.stop()
        logger.info("=== Arrêt terminé ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())