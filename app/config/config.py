"""Configuration statique du backend (matériel, base, logs).

Ces paramètres décrivent l'environnement d'exécution (port série, broche GPIO,
chemin de la base, logs). Ils sont distincts des ``Setting`` applicatifs
(modifiables à chaud depuis l'interface) : ici, il s'agit du câblage bas niveau,
figé au démarrage et surchargeable par variables d'environnement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Racine du projet (…/garage-controller).
BASE_DIR = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "oui"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class Config:
    """Paramètres d'environnement du backend."""

    # Base de données
    database_url: str = f"sqlite:///{BASE_DIR / 'instance' / 'garage.db'}"

    # Modem SIM800
    serial_port: str = "/dev/serial0"
    serial_baudrate: int = 115200

    # Relais (GPIO)
    gpio_relay_pin: int = 17
    # La plupart des modules relais optocouplés sont *actifs à l'état bas* :
    # la broche doit être HAUTE au repos et passer BASSE pour activer le relais.
    # Sinon le relais reste enclenché en permanence au démarrage.
    # Forcer un autre comportement via GARAGE_RELAY_ACTIVE_HIGH=1.
    relay_active_high: bool = False

    # Logs
    log_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")
    log_level: str = "INFO"
    log_max_bytes: int = 1_048_576  # 1 Mio
    log_backup_count: int = 5

    # Interface web
    web_enabled: bool = True
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    # Dev : n'utilise pas de vrai port série (aucun matériel requis).
    fake_serial: bool = False
    sql_echo: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        """Construit la configuration à partir des variables d'environnement."""
        return cls(
            database_url=os.environ.get("GARAGE_DATABASE_URL", cls.database_url),
            serial_port=os.environ.get("GARAGE_SERIAL_PORT", cls.serial_port),
            serial_baudrate=_env_int("GARAGE_SERIAL_BAUDRATE", cls.serial_baudrate),
            gpio_relay_pin=_env_int("GARAGE_RELAY_PIN", cls.gpio_relay_pin),
            relay_active_high=_env_bool("GARAGE_RELAY_ACTIVE_HIGH", cls.relay_active_high),
            log_dir=Path(os.environ.get("GARAGE_LOG_DIR", str(BASE_DIR / "logs"))),
            log_level=os.environ.get("GARAGE_LOG_LEVEL", cls.log_level),
            web_enabled=_env_bool("GARAGE_WEB_ENABLED", cls.web_enabled),
            web_host=os.environ.get("GARAGE_WEB_HOST", cls.web_host),
            web_port=_env_int("GARAGE_WEB_PORT", cls.web_port),
            fake_serial=_env_bool("GARAGE_FAKE_SERIAL", cls.fake_serial),
            sql_echo=_env_bool("GARAGE_SQL_ECHO", cls.sql_echo),
        )
