"""SettingsService : accès typé et caché aux paramètres (``Setting``)."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from app.database import SessionFactory, session_scope
from app.models import Setting

logger = logging.getLogger(__name__)

# Valeurs par défaut, cohérentes avec docs/spec-sms.md et docs/spec-gsm.md.
# Toutes les valeurs sont stockées en base sous forme de chaînes.
DEFAULT_SETTINGS: Dict[str, str] = {
    # Appels
    "call_answer_duration_seconds": "2.0",
    "relay_pulse_seconds": "0.5",
    # SMS
    "sms_enabled": "true",
    "sms_command_open": "OUVRE",
    "sms_command_pin": "",
    "sms_reply_enabled": "false",
    "sms_reply_text": "Garage ouvert",
    "min_interval_sms_open_seconds": "30",
    # Rapport quotidien
    "report_enabled": "false",
    "report_time": "20:00",
    "report_recipients": "[]",  # JSON : liste de numéros
    "report_include_sms": "true",
}

_TRUE_VALUES = {"1", "true", "yes", "on", "oui"}


class SettingsService:
    """Lit/écrit les paramètres avec cache mémoire et fallback par défaut."""

    def __init__(
        self,
        session_factory: SessionFactory,
        defaults: Optional[Dict[str, str]] = None,
    ) -> None:
        self._session_factory = session_factory
        self._defaults = dict(defaults or DEFAULT_SETTINGS)
        self._cache: Dict[str, str] = {}
        self._cache_loaded = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Cache
    # ------------------------------------------------------------------ #
    def _ensure_cache(self) -> None:
        if self._cache_loaded:
            return
        with self._lock:
            if self._cache_loaded:
                return
            with session_scope(self._session_factory) as session:
                rows = session.query(Setting).all()
                self._cache = {row.key: row.value for row in rows if row.value is not None}
            self._cache_loaded = True

    def invalidate_cache(self) -> None:
        """Force le rechargement du cache au prochain accès."""
        with self._lock:
            self._cache.clear()
            self._cache_loaded = False

    def ensure_defaults(self) -> None:
        """Insère en base les clés par défaut manquantes (idempotent)."""
        with self._lock:
            with session_scope(self._session_factory) as session:
                existing = {row.key for row in session.query(Setting.key).all()}
                for key, value in self._defaults.items():
                    if key not in existing:
                        session.add(Setting(key=key, value=value))
        self.invalidate_cache()

    # ------------------------------------------------------------------ #
    # Lecture typée
    # ------------------------------------------------------------------ #
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retourne la valeur brute (str) d'une clé, avec fallback défaut."""
        self._ensure_cache()
        if key in self._cache:
            return self._cache[key]
        if key in self._defaults:
            return self._defaults[key]
        return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key)
        if value is None:
            return default
        return value.strip().lower() in _TRUE_VALUES

    def get_int(self, key: str, default: int = 0) -> int:
        value = self.get(key)
        try:
            return int(float(value)) if value is not None else default
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        value = self.get(key)
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    def get_json(self, key: str, default: Any = None) -> Any:
        value = self.get(key)
        if not value:
            return default
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            logger.warning("Setting %s n'est pas du JSON valide : %r", key, value)
            return default

    def get_list(self, key: str) -> List[str]:
        """Retourne une liste de chaînes (stockée en JSON)."""
        value = self.get_json(key, default=[])
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    # ------------------------------------------------------------------ #
    # Écriture
    # ------------------------------------------------------------------ #
    def set(self, key: str, value: Any) -> None:
        """Écrit/actualise une valeur (sérialise bool/list/dict au besoin)."""
        serialized = self._serialize(value)
        with self._lock:
            with session_scope(self._session_factory) as session:
                setting = session.get(Setting, key)
                if setting is None:
                    session.add(Setting(key=key, value=serialized))
                else:
                    setting.value = serialized
            self._cache[key] = serialized

    @staticmethod
    def _serialize(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
