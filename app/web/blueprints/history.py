"""Blueprint historique des appels/SMS + export CSV."""

from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, render_template, request

from app.web.helpers import get_services
from app.web.security import login_required

bp = Blueprint("history", __name__, url_prefix="/history")


@bp.route("/")
@login_required
def index():
    limit = request.args.get("limit", default=100, type=int)
    entries = get_services().history.list_recent(limit=limit)
    return render_template("history.html", entries=entries, limit=limit)


@bp.route("/export.csv")
@login_required
def export_csv():
    entries = get_services().history.list_recent(limit=5000)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["date", "source", "numero", "autorise", "repondu", "relais", "duree_s"]
    )
    for entry in entries:
        writer.writerow([
            entry.date.strftime("%Y-%m-%d %H:%M:%S"),
            entry.source,
            entry.phone_number,
            int(entry.authorized),
            int(entry.answered),
            int(entry.relay_triggered),
            "" if entry.duration is None else f"{entry.duration:.1f}",
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=historique.csv"},
    )
