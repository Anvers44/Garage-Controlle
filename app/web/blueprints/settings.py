"""Blueprint paramètres : édition des ``Setting`` applicatifs + mot de passe."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.web.helpers import get_services
from app.web.security import login_required

bp = Blueprint("settings", __name__, url_prefix="/settings")

# Clés booléennes (cases à cocher).
_BOOL_KEYS = (
    "sms_enabled",
    "sms_reply_enabled",
    "report_enabled",
    "report_include_sms",
)
# Clés texte / numériques (champs libres).
_TEXT_KEYS = (
    "call_answer_duration_seconds",
    "relay_pulse_seconds",
    "sms_command_open",
    "sms_command_pin",
    "sms_reply_text",
    "min_interval_sms_open_seconds",
    "report_time",
)


@bp.route("/")
@login_required
def index():
    settings = get_services().settings
    values = {key: settings.get(key) for key in _TEXT_KEYS}
    values.update({key: settings.get_bool(key) for key in _BOOL_KEYS})
    recipients = ", ".join(settings.get_list("report_recipients"))
    return render_template(
        "settings.html",
        values=values,
        recipients=recipients,
        uses_default_password=get_services().auth.uses_default_password,
    )


@bp.route("/", methods=["POST"])
@login_required
def save():
    settings = get_services().settings
    for key in _TEXT_KEYS:
        if key in request.form:
            settings.set(key, request.form.get(key, "").strip())
    for key in _BOOL_KEYS:
        settings.set(key, request.form.get(key) == "on")

    # Destinataires du rapport : liste séparée par virgules -> JSON.
    raw = request.form.get("report_recipients", "")
    recipients = [item.strip() for item in raw.split(",") if item.strip()]
    settings.set("report_recipients", recipients)

    flash("Paramètres enregistrés.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/password", methods=["POST"])
@login_required
def change_password():
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if new_password != confirm:
        flash("Les mots de passe ne correspondent pas.", "danger")
        return redirect(url_for("settings.index"))
    try:
        get_services().auth.set_password(new_password)
        flash("Mot de passe modifié.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("settings.index"))


@bp.route("/report/test", methods=["POST"])
@login_required
def test_report():
    ok = get_services().gsm.send_daily_report_now()
    flash(
        "Rapport de test envoyé." if ok else "Envoi impossible (destinataires ? modem ?).",
        "success" if ok else "danger",
    )
    return redirect(url_for("settings.index"))
