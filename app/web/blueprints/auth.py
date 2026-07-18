"""Blueprint d'authentification (login / logout)."""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.web.helpers import get_services
from app.web.security import current_user, login_user, logout_user

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Affiche et traite le formulaire de connexion."""
    if current_user():
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if get_services().auth.verify(username, password):
            login_user(username)
            flash("Connexion réussie.", "success")
            target = request.args.get("next") or url_for("dashboard.index")
            return redirect(target)
        flash("Identifiants invalides.", "danger")

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    """Déconnecte l'utilisateur courant."""
    logout_user()
    flash("Déconnexion effectuée.", "success")
    return redirect(url_for("auth.login"))
