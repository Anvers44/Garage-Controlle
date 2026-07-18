"""Sécurité de l'interface web : session de connexion et protection CSRF.

Implémentation volontairement légère (sans Flask-WTF) : un jeton CSRF par
session est injecté dans les templates et vérifié sur toute requête mutante.
"""

from __future__ import annotations

import secrets
from functools import wraps
from typing import Callable

from flask import (
    Flask,
    abort,
    current_app,
    redirect,
    request,
    session,
    url_for,
)

_CSRF_SESSION_KEY = "_csrf_token"
_USER_SESSION_KEY = "user"
# Méthodes HTTP considérées comme mutantes → CSRF requis.
_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def init_security(app: Flask) -> None:
    """Installe la protection CSRF et l'injection du jeton dans les templates."""

    @app.before_request
    def _csrf_protect() -> None:
        if request.method in _PROTECTED_METHODS:
            expected = session.get(_CSRF_SESSION_KEY)
            provided = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not expected or not provided or not secrets.compare_digest(expected, provided):
                abort(400, description="Jeton CSRF invalide ou manquant.")

    @app.context_processor
    def _inject_csrf() -> dict:
        token = session.get(_CSRF_SESSION_KEY)
        if not token:
            token = secrets.token_hex(16)
            session[_CSRF_SESSION_KEY] = token
        return {"csrf_token": token}


def login_user(username: str) -> None:
    """Marque la session comme authentifiée."""
    session[_USER_SESSION_KEY] = username


def logout_user() -> None:
    """Efface la session d'authentification."""
    session.pop(_USER_SESSION_KEY, None)


def current_user() -> str | None:
    """Retourne l'utilisateur connecté, ou ``None``."""
    return session.get(_USER_SESSION_KEY)


def login_required(view: Callable) -> Callable:
    """Décorateur : redirige vers la page de login si non authentifié."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped
