"""Blueprint relais : état, historique et déclenchement manuel."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for

from app.models import RELAY_SOURCE_MANUAL
from app.web.helpers import get_services
from app.web.security import login_required

bp = Blueprint("relay", __name__, url_prefix="/relay")


@bp.route("/")
@login_required
def index():
    services = get_services()
    pulse = services.settings.get_float("relay_pulse_seconds", default=0.5)
    events = services.relay.recent(limit=50)
    return render_template(
        "relay.html",
        active=services.relay.is_active,
        pulse=pulse,
        events=events,
    )


@bp.route("/trigger", methods=["POST"])
@login_required
def trigger():
    """Déclenche manuellement le relais (source ``manual``)."""
    try:
        get_services().relay.trigger(
            source=RELAY_SOURCE_MANUAL,
            metadata={"origin": "web"},
        )
        flash("Relais déclenché.", "success")
    except Exception:  # pragma: no cover - dépend du GPIO
        flash("Échec du déclenchement du relais.", "danger")
    return redirect(url_for("relay.index"))
