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
    GARAGE_RELAY_PIN=17
"""

from __future__ import annotations

import logging
import signal
import threading

from app.backend import Backend
from app.config import Config
from app.utils.logging import setup_logging

logger = logging.getLogger("garage.run")


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

    try:
        if config.web_enabled:
            _run_web(backend, config, stop_event)
        else:
            _run_headless(backend, stop_event)
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        backend.stop()
        logger.info("=== Arrêt terminé ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
