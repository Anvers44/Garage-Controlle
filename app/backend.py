"""Amorçage du backend : câble config → base → matériel → services.

Ce module constitue le point d'entrée réutilisable du cœur applicatif. Il est
utilisé par ``run.py`` (exécution en service) et pourra l'être par la future
couche web Flask, qui partagera le même ``ServiceContainer``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.config import Config
from app.database import Database
from app.hardware.gpio import RelayDriver
from app.hardware.monitoring import SystemMonitor
from app.hardware.sim800 import SIM800
from app.services import ServiceContainer, build_services

logger = logging.getLogger(__name__)


class Backend:
    """Regroupe les objets bas niveau et les services, avec start/stop."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.database = Database(config.database_url, echo=config.sql_echo)
        self.sim800 = self._create_sim800(config)
        self.relay = RelayDriver(
            pin=config.gpio_relay_pin,
            active_high=config.relay_active_high,
        )
        self.monitor = SystemMonitor()
        self.services: Optional[ServiceContainer] = None
        self._started = False

    @staticmethod
    def _create_sim800(config: Config) -> SIM800:
        if config.fake_serial:
            from app.hardware.fake_serial import FakeSerial

            def factory(port, baud, timeout=None):
                return FakeSerial(port, baud, timeout)

            return SIM800(
                port=config.serial_port,
                baudrate=config.serial_baudrate,
                serial_factory=factory,
            )
        return SIM800(port=config.serial_port, baudrate=config.serial_baudrate)

    def initialize(self) -> ServiceContainer:
        """Crée le schéma de base et câble les services (sans démarrer le GSM)."""
        self._ensure_sqlite_dir(self.config.database_url)
        self.database.create_all()
        self.services = build_services(self.database, self.sim800, self.relay)
        logger.info("Backend initialisé (db=%s)", self.config.database_url)
        return self.services

    def start(self) -> None:
        """Démarre le service GSM (threads série, scheduler de rapport)."""
        if self.services is None:
            self.initialize()
        assert self.services is not None
        self.services.gsm.start()
        self._started = True
        logger.info("Backend démarré.")

    def stop(self) -> None:
        """Arrête proprement le GSM et libère le GPIO."""
        if self.services is not None and self._started:
            self.services.gsm.stop()
        try:
            self.relay.cleanup()
        except Exception:  # pragma: no cover - best effort
            logger.exception("Erreur au cleanup du relais")
        self._started = False
        logger.info("Backend arrêté.")

    @staticmethod
    def _ensure_sqlite_dir(database_url: str) -> None:
        """Crée le dossier parent d'une base SQLite fichier si nécessaire."""
        prefix = "sqlite:///"
        if not database_url.startswith(prefix) or ":memory:" in database_url:
            return
        db_path = Path(database_url[len(prefix):])
        db_path.parent.mkdir(parents=True, exist_ok=True)


def create_backend(config: Optional[Config] = None) -> Backend:
    """Fabrique un ``Backend`` initialisé (schéma créé, services câblés)."""
    backend = Backend(config or Config.from_env())
    backend.initialize()
    return backend
