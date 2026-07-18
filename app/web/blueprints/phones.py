"""Blueprint CRUD des numéros autorisés (whitelist)."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.web.helpers import get_services
from app.web.security import login_required

bp = Blueprint("phones", __name__, url_prefix="/phones")


@bp.route("/")
@login_required
def index():
    phones = get_services().phones.list_phones()
    return render_template("phones.html", phones=phones)


@bp.route("/add", methods=["POST"])
@login_required
def add():
    number = request.form.get("number", "").strip()
    name = request.form.get("name", "").strip() or None
    enabled = request.form.get("enabled") == "on"
    try:
        get_services().phones.add_phone(number, name=name, enabled=enabled)
        flash(f"Numéro {number} ajouté.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("phones.index"))


@bp.route("/<int:phone_id>/edit", methods=["POST"])
@login_required
def edit(phone_id: int):
    name = request.form.get("name", "").strip() or None
    enabled = request.form.get("enabled") == "on"
    updated = get_services().phones.update_phone(phone_id, name=name, enabled=enabled)
    flash("Numéro mis à jour." if updated else "Numéro introuvable.",
          "success" if updated else "danger")
    return redirect(url_for("phones.index"))


@bp.route("/<int:phone_id>/toggle", methods=["POST"])
@login_required
def toggle(phone_id: int):
    services = get_services()
    phone = None
    for candidate in services.phones.list_phones():
        if candidate.id == phone_id:
            phone = candidate
            break
    if phone is None:
        flash("Numéro introuvable.", "danger")
    else:
        services.phones.set_enabled(phone_id, not phone.enabled)
        flash("État du numéro modifié.", "success")
    return redirect(url_for("phones.index"))


@bp.route("/<int:phone_id>/delete", methods=["POST"])
@login_required
def delete(phone_id: int):
    ok = get_services().phones.delete_phone(phone_id)
    flash("Numéro supprimé." if ok else "Numéro introuvable.",
          "success" if ok else "danger")
    return redirect(url_for("phones.index"))
