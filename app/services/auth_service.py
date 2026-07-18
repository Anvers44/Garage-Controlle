"""AuthService : authentification locale de l'interface web.

Les identifiants sont stockés dans ``Setting`` (mot de passe haché via
Werkzeug). Au premier démarrage, un compte ``admin`` / ``admin`` est créé et
marqué comme « par défaut » afin que l'interface invite à le changer.
"""

from __future__ import annotations

import logging
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

_KEY_USER = "web_admin_user"
_KEY_HASH = "web_admin_password_hash"
_KEY_IS_DEFAULT = "web_password_is_default"
_KEY_SECRET = "web_secret_key"

_DEFAULT_USER = "admin"
_DEFAULT_PASSWORD = "admin"


class AuthService:
    """Gère l'unique compte administrateur de l'interface web."""

    def __init__(self, settings_service: SettingsService) -> None:
        self._settings = settings_service

    def ensure_admin(self) -> None:
        """Crée le compte admin par défaut s'il n'existe pas encore."""
        if not self._settings.get(_KEY_HASH):
            self._settings.set(_KEY_USER, _DEFAULT_USER)
            self._settings.set(_KEY_HASH, generate_password_hash(_DEFAULT_PASSWORD))
            self._settings.set(_KEY_IS_DEFAULT, True)
            logger.warning(
                "Compte admin par défaut créé (admin/admin) : à changer via Paramètres."
            )

    def verify(self, username: str, password: str) -> bool:
        """Vérifie un couple identifiant / mot de passe."""
        expected_user = self._settings.get(_KEY_USER, _DEFAULT_USER)
        password_hash = self._settings.get(_KEY_HASH)
        if not password_hash or username != expected_user:
            return False
        return check_password_hash(password_hash, password)

    def set_password(self, new_password: str) -> None:
        """Change le mot de passe admin (et lève le marqueur « par défaut »)."""
        if not new_password or len(new_password) < 4:
            raise ValueError("Le mot de passe doit contenir au moins 4 caractères.")
        self._settings.set(_KEY_HASH, generate_password_hash(new_password))
        self._settings.set(_KEY_IS_DEFAULT, False)
        logger.info("Mot de passe admin modifié.")

    @property
    def username(self) -> str:
        return self._settings.get(_KEY_USER, _DEFAULT_USER)

    @property
    def uses_default_password(self) -> bool:
        return self._settings.get_bool(_KEY_IS_DEFAULT, default=False)

    def get_or_create_secret_key(self) -> str:
        """Retourne (en la créant au besoin) la clé secrète Flask persistée."""
        secret = self._settings.get(_KEY_SECRET)
        if not secret:
            secret = secrets.token_hex(32)
            self._settings.set(_KEY_SECRET, secret)
        return secret
