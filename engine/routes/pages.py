"""Server-rendered page shells. Live data is loaded by the page scripts from /api."""
from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, url_for

bp = Blueprint("pages", __name__)


def c():
    return current_app.extensions["pe3k"]


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", page="dashboard")


@bp.get("/devices")
def devices():
    return render_template("devices.html", page="devices")


@bp.get("/alerts")
def alerts():
    return render_template("alerts.html", page="alerts")


@bp.get("/history")
@bp.get("/history/<int:device_id>")
def history(device_id: int | None = None):
    devices = c().devices.list()
    if device_id is None and devices:
        device_id = request.args.get("device", type=int) or devices[0]["id"]
        return redirect(url_for("pages.history", device_id=device_id))
    return render_template("history.html", page="history", devices=devices, device_id=device_id)


@bp.get("/bandwidth")
def bandwidth():
    return render_template("bandwidth.html", page="bandwidth")


@bp.get("/settings")
def settings():
    return render_template("settings.html", page="settings")


@bp.get("/healthz")
def healthz():
    k = c()
    with k.db.session() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "scheduler": bool(k.scheduler and k.scheduler.started)}
