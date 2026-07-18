"""Blueprint dashboard + statut GSM + actions modem."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, url_for

from app import __version__
from app.web.helpers import get_backend, get_services
from app.web.security import login_required

bp = Blueprint("dashboard", __name__)


def _collect_status() -> dict:
    """Agrège toutes les données affichées sur le dashboard."""
    backend = get_backend()
    services = get_services()
    today = date.today()
    stats = services.history.get_daily_stats(today)
    gsm = services.gsm.get_status()
    return {
        "system": backend.monitor.get_stats(),
        "gsm": gsm,
        "relay": {"active": services.relay.is_active},
        "stats": {
            "total_calls": stats.total_calls,
            "authorized_calls": stats.authorized_calls,
            "call_openings": stats.call_openings,
            "sms_openings": stats.sms_openings,
            "refused_attempts": stats.refused_attempts,
        },
        "version": __version__,
    }


@bp.route("/")
@login_required
def index():
    """Page dashboard (les données dynamiques sont chargées via /api/status)."""
    return render_template("dashboard.html", data=_collect_status())


@bp.route("/api/status")
@login_required
def api_status():
    """Endpoint JSON pour le rafraîchissement AJAX du dashboard."""
    return jsonify(_collect_status())


@bp.route("/gsm")
@login_required
def gsm():
    """Page GSM détaillée."""
    status = get_services().gsm.get_status(force=True)
    return render_template("gsm.html", status=status)


@bp.route("/gsm/test", methods=["POST"])
@login_required
def gsm_test():
    """Teste la communication avec le modem."""
    ok = get_services().gsm.test_communication()
    flash("Communication modem OK." if ok else "Modem injoignable.", "success" if ok else "danger")
    return redirect(url_for("dashboard.gsm"))


@bp.route("/gsm/reboot", methods=["POST"])
@login_required
def gsm_reboot():
    """Redémarre le modem."""
    try:
        get_services().gsm.reboot_modem()
        flash("Redémarrage du modem demandé.", "success")
    except Exception:  # pragma: no cover - dépend du modem
        flash("Échec du redémarrage du modem.", "danger")
    return redirect(url_for("dashboard.gsm"))
