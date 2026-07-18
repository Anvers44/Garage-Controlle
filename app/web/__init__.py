"""Couche web Flask.

Couche de présentation uniquement : les routes orchestrent les services et
sérialisent, sans logique métier (voir ``CLAUDE.md``). Tout est servi en local
(CSS/JS embarqués, aucun CDN) pour fonctionner sur le point d'accès Wi-Fi hors
ligne du Raspberry Pi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from flask import Flask, render_template

from app.web.blueprints import (
    auth,
    dashboard,
    history,
    phones,
    relay,
    settings,
)
from app.web.helpers import format_bytes, format_duration
from app.web.security import current_user, init_security

if TYPE_CHECKING:  # pragma: no cover
    from app.backend import Backend


def create_app(backend: "Backend", secret_key: Optional[str] = None) -> Flask:
    """Crée l'application Flask partageant le ``ServiceContainer`` du backend.

    Args:
        backend: backend déjà initialisé (``backend.services`` non nul).
        secret_key: clé secrète de session ; si ``None``, on réutilise celle
            persistée par ``AuthService`` (sessions stables entre redémarrages).
    """
    assert backend.services is not None, "Le backend doit être initialisé"

    app = Flask(__name__)
    app.config["BACKEND"] = backend
    app.secret_key = secret_key or backend.services.auth.get_or_create_secret_key()

    init_security(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(phones.bp)
    app.register_blueprint(history.bp)
    app.register_blueprint(relay.bp)
    app.register_blueprint(settings.bp)

    # Filtres Jinja utilitaires.
    app.jinja_env.filters["bytes"] = format_bytes
    app.jinja_env.filters["duration"] = format_duration

    @app.context_processor
    def _inject_globals() -> dict:
        return {"current_user": current_user()}

    @app.errorhandler(400)
    def _bad_request(error):  # pragma: no cover - rendu d'erreur
        return render_template("error.html", code=400, message=error.description), 400

    @app.errorhandler(404)
    def _not_found(error):  # pragma: no cover - rendu d'erreur
        return render_template("error.html", code=404, message="Page introuvable."), 404

    return app
