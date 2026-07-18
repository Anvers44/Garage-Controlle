"""Helpers partagés par les blueprints web."""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import current_app

if TYPE_CHECKING:  # pragma: no cover
    from app.backend import Backend
    from app.services import ServiceContainer


def get_backend() -> "Backend":
    """Retourne le ``Backend`` partagé stocké dans la config Flask."""
    return current_app.config["BACKEND"]


def get_services() -> "ServiceContainer":
    """Retourne le ``ServiceContainer`` câblé."""
    services = get_backend().services
    assert services is not None, "Backend non initialisé"
    return services


def format_bytes(value: int | None) -> str:
    """Formate un nombre d'octets en unité lisible (Kio/Mio/Gio)."""
    if value is None:
        return "-"
    size = float(value)
    for unit in ("o", "Kio", "Mio", "Gio", "Tio"):
        if size < 1024.0:
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} Pio"


def format_duration(seconds: float | None) -> str:
    """Formate une durée en ``Jj HHhMM`` / ``HHhMM`` / ``MMmSS``."""
    if seconds is None:
        return "-"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}j {hours:02d}h{minutes:02d}"
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes}m{secs:02d}"
