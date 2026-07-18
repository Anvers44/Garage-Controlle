"""Configuration du logging applicatif (console + fichier avec rotation)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    max_bytes: int = 1_048_576,
    backup_count: int = 5,
    filename: str = "garage.log",
) -> None:
    """Configure le logger racine (idempotent).

    Args:
        log_dir: répertoire des fichiers de log (créé si absent).
        level: niveau de log (``"DEBUG"``, ``"INFO"``, …).
        max_bytes: taille max d'un fichier avant rotation.
        backup_count: nombre de fichiers de rotation conservés.
        filename: nom du fichier de log principal.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Évite la duplication des handlers en cas d'appel multiple.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_dir / filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
