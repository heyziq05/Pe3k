"""CSV download endpoints."""
from __future__ import annotations

import re

from flask import Blueprint, Response, current_app, request

from ..services import export_service as ex
from ..services import uptime as uptime_svc
from ..services.device_service import NotFound
from ..timeutil import WINDOWS, resolve_range, window_start

bp = Blueprint("exports", __name__)


def c():
    return current_app.extensions["pe3k"]


def _window(default: str) -> str:
    w = request.args.get("window", default)
    return w if w in WINDOWS or w == "all" else default


def _csv(text: str, prefix: str) -> Response:
    return Response(
        text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{ex.filename(prefix)}"', "Cache-Control": "no-store"},
    )


@bp.get("/devices.csv")
def devices_csv():
    return _csv(ex.to_csv(ex.DEVICE_COLUMNS, c().devices.list()), "devices")


@bp.get("/devices/<int:device_id>/history.csv")
def device_history_csv(device_id: int):
    k = c()
    try:
        device = k.devices.get(device_id)
    except NotFound:
        return Response("Device not found", 404)
    window = _window("7d")
    start = window_start(window)
    sql = "SELECT checked_at, success, latency_ms, status_after, attempts, error FROM monitor_logs WHERE device_id = ?"
    params: list = [device_id]
    if start:
        sql += " AND checked_at >= ?"
        params.append(start)
    with k.db.session() as conn:
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY checked_at, id", params)]
    slug = re.sub(r"[^a-z0-9]+", "-", device["name"].lower()).strip("-") or f"device-{device_id}"
    return _csv(ex.to_csv(ex.HISTORY_COLUMNS, rows), f"history-{slug}-{window}")


@bp.get("/alerts.csv")
def alerts_csv():
    a = request.args
    status = a.get("status", "all")
    try:
        start, end, label = resolve_range(a.get("window", "all"), a.get("since"), a.get("until"))
    except ValueError as exc:
        return Response(str(exc), 400, mimetype="text/plain")
    rows = c().alerts.list(status=status, alert_type=a.get("type", ""), limit=50000, since=start, until=end)
    return _csv(ex.to_csv(ex.ALERT_COLUMNS, rows), f"alerts-{status}-{label}")


@bp.get("/bandwidth.csv")
def bandwidth_csv():
    k = c()
    window = _window("7d")
    iface = request.args.get("interface") or None
    return _csv(ex.to_csv(ex.BANDWIDTH_COLUMNS, k.bandwidth.logs(window, iface)), f"bandwidth-{window}")


@bp.get("/uptime.csv")
def uptime_csv():
    window = _window("24h")
    return _csv(ex.to_csv(ex.UPTIME_COLUMNS, uptime_svc.uptime_summary(c().db, window)), f"uptime-{window}")
