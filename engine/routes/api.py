"""JSON API consumed by the Pe3k front end."""
from __future__ import annotations

import ipaddress
import logging
import platform
import socket
import sys
from functools import wraps
from importlib import metadata

import psutil
from flask import Blueprint, current_app, jsonify, request

from ..monitoring.bandwidth import list_interfaces
from ..monitoring.discovery import ENGINE_LABELS
from ..monitoring.scan_service import ScanInProgress
from ..monitoring.discovery.base import ScannerError
from ..monitoring.system import IS_WINDOWS, is_admin, npcap_installed
from ..services import uptime as uptime_svc
from ..services.device_service import NotFound
from ..services.maintenance import ResetBlocked, factory_reset, reset_settings
from ..services.settings_service import ADVANCED_KEYS, SIMPLE_PRESET
from ..timeutil import WINDOWS, now_iso, resolve_range, window_start
from ..validators import DEVICE_TYPE_LABELS, STRICT_MIN_PREFIX, ValidationError

bp = Blueprint("api", __name__)
log = logging.getLogger("pe3k.api")


def c():
    return current_app.extensions["pe3k"]


def body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def handle_errors(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValidationError as exc:
            return jsonify(error="Please fix the highlighted fields.", fields=exc.errors), 400
        except NotFound as exc:
            return jsonify(error=str(exc)), 404
        except ScanInProgress as exc:
            return jsonify(error=str(exc)), 409
        except ScannerError as exc:
            return jsonify(error=str(exc)), 422
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    return wrapper


def _window(default: str = "24h") -> str:
    w = request.args.get("window", default)
    return w if w in WINDOWS or w == "all" else default


# ------------------------------------------------------------------ overview
@bp.get("/nav")
@handle_errors
def nav():
    k = c()
    cfg = k.settings.all()
    engine = cfg["discovery_engine"]
    return jsonify(
        alerts_open=k.alerts.counts()["open"],
        scan={"engine": engine, "engine_label": ENGINE_LABELS.get(engine, engine), "running": k.scans.running,
              "ready": k.scans.health(engine).ready},
    )


@bp.get("/overview")
@handle_errors
def overview():
    k = c()
    bw = k.bandwidth_monitor.snapshot()
    iface = bw["interface"]
    return jsonify(
        devices=k.devices.counts(),
        alerts=k.alerts.counts(),
        scan=k.scans.status(),
        bandwidth={
            "interface": iface,
            "error": bw["error"],
            "current": bw["current"],
            "live": bw["live"][-120:],
            "today": k.bandwidth.today(iface),
        },
        device_list=k.devices.list(),
        recent_alerts=k.alerts.list(status="open", limit=6),
        last_ping_cycle=k.monitor.last_cycle,
        demo_mode=k.demo_mode,
        server_time=now_iso(),
    )


@bp.get("/latency")
@handle_errors
def latency():
    """Fleet latency over time: average and worst device per bucket (one unit, one axis)."""
    window = _window("6h")
    bucket = {"1h": 60, "6h": 300, "24h": 900, "7d": 3600, "30d": 4 * 3600}.get(window, 300)
    device_id = request.args.get("device_id", type=int)
    params: list = [bucket, window_start(window)]
    inner = (
        "SELECT (CAST(strftime('%s', checked_at) AS INTEGER) / ?) AS b, device_id, AVG(latency_ms) AS lat,"
        " SUM(success) AS ok, COUNT(*) AS n FROM monitor_logs WHERE checked_at >= ?"
    )
    if device_id:
        inner += " AND device_id = ?"
        params.append(device_id)
    inner += " GROUP BY b, device_id"
    sql = (f"SELECT b, AVG(lat) AS avg_lat, MAX(lat) AS max_lat, SUM(ok) AS ok, SUM(n) AS n FROM ({inner}) GROUP BY b ORDER BY b")
    from datetime import datetime, timezone

    with c().db.session() as conn:
        rows = conn.execute(sql, params).fetchall()
    points = [
        {
            "t": datetime.fromtimestamp(r["b"] * bucket, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "avg_ms": round(r["avg_lat"], 2) if r["avg_lat"] is not None else None,
            "max_ms": round(r["max_lat"], 2) if r["max_lat"] is not None else None,
            "success_rate": round(100 * r["ok"] / r["n"], 1) if r["n"] else None,
        }
        for r in rows
    ]
    return jsonify(window=window, bucket_seconds=bucket, points=points)


# ------------------------------------------------------------------- devices
@bp.get("/devices")
@handle_errors
def devices_list():
    a = request.args
    return jsonify(devices=c().devices.list(a.get("search", ""), a.get("status", ""), a.get("type", ""), a.get("trusted", "")),
                   counts=c().devices.counts(), types=DEVICE_TYPE_LABELS)


@bp.post("/devices")
@handle_errors
def devices_create():
    return jsonify(device=c().devices.create(body())), 201


@bp.get("/devices/<int:device_id>")
@handle_errors
def devices_get(device_id: int):
    return jsonify(device=c().devices.get(device_id))


@bp.put("/devices/<int:device_id>")
@handle_errors
def devices_update(device_id: int):
    return jsonify(device=c().devices.update(device_id, body()))


@bp.delete("/devices/<int:device_id>")
@handle_errors
def devices_delete(device_id: int):
    c().devices.delete(device_id)
    return jsonify(ok=True)


@bp.post("/devices/<int:device_id>/trust")
@handle_errors
def devices_trust(device_id: int):
    trusted = body().get("trusted", True)
    return jsonify(device=c().devices.set_trusted(device_id, bool(trusted)))


@bp.post("/devices/<int:device_id>/check")
@handle_errors
def devices_check(device_id: int):
    device = c().devices.get(device_id)
    result = c().monitor.check_device(device)
    return jsonify(result=result, device=c().devices.get(device_id))


@bp.get("/devices/<int:device_id>/history")
@handle_errors
def devices_history(device_id: int):
    k = c()
    window = _window("24h")
    device = k.devices.get(device_id)
    page = max(1, request.args.get("page", 1, type=int))
    per_page = max(10, min(request.args.get("per_page", 50, type=int), 200))
    start = window_start(window)
    params: list = [device_id]
    where = "device_id = ?"
    if start:
        where += " AND checked_at >= ?"
        params.append(start)
    with k.db.session() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM monitor_logs WHERE {where}", params).fetchone()[0]
        checks = [dict(r) for r in conn.execute(
            f"SELECT checked_at, success, latency_ms, status_after, attempts, error FROM monitor_logs WHERE {where}"
            " ORDER BY checked_at DESC, id DESC LIMIT ? OFFSET ?", [*params, per_page, (page - 1) * per_page])]
    return jsonify(
        device=device,
        window=window,
        uptime=uptime_svc.device_uptime(k.db, device_id, window),
        uptime_windows={w: uptime_svc.device_uptime(k.db, device_id, w)["uptime_percent"] for w in ("24h", "7d", "30d")},
        outages=uptime_svc.device_outages(k.db, device_id, window if window != "1h" else "24h"),
        checks=checks,
        page=page, per_page=per_page, total=total,
    )


@bp.get("/uptime")
@handle_errors
def uptime_summary():
    return jsonify(window=_window("24h"), devices=uptime_svc.uptime_summary(c().db, _window("24h")))


# -------------------------------------------------------------------- alerts
@bp.get("/alerts")
@handle_errors
def alerts_list():
    status = request.args.get("status", "open")
    a = request.args
    start, end, label = resolve_range(a.get("window", "all"), a.get("since"), a.get("until"))
    return jsonify(alerts=c().alerts.list(status=status, alert_type=a.get("type", ""), since=start, until=end),
                   counts=c().alerts.counts(), range={"window": label, "since": start, "until": end})


@bp.post("/alerts/<int:alert_id>/<action>")
@handle_errors
def alerts_action(alert_id: int, action: str):
    if action == "trust":
        device = c().alerts.trust(alert_id, body())
        return jsonify(device=device, alert=c().alerts.get(alert_id))
    if action not in ("ignore", "resolve", "reopen"):
        return jsonify(error="Unknown action"), 404
    return jsonify(alert=c().alerts.set_status(alert_id, action))


# ----------------------------------------------------------------- bandwidth
@bp.get("/bandwidth/live")
@handle_errors
def bandwidth_live():
    k = c()
    snap = k.bandwidth_monitor.snapshot()
    snap["today"] = k.bandwidth.today(snap["interface"])
    return jsonify(snap)


@bp.get("/bandwidth/history")
@handle_errors
def bandwidth_history():
    k = c()
    iface = request.args.get("interface") or k.bandwidth_monitor.interface()
    window = _window("24h")
    return jsonify(window=window, interface=iface, points=k.bandwidth.history(window, iface),
                   totals=k.bandwidth.totals(window, iface))


@bp.get("/bandwidth/daily")
@handle_errors
def bandwidth_daily():
    k = c()
    iface = request.args.get("interface") or k.bandwidth_monitor.interface()
    return jsonify(interface=iface, days=k.bandwidth.daily_totals(request.args.get("days", 14, type=int), iface))


@bp.get("/bandwidth/interfaces")
@handle_errors
def bandwidth_interfaces():
    return jsonify(selected=c().bandwidth_monitor.interface(), interfaces=list_interfaces())


@bp.put("/bandwidth/interface")
@handle_errors
def bandwidth_set_interface():
    name = str(body().get("interface") or "all")
    if name != "all" and name not in {i["name"] for i in list_interfaces()}:
        raise ValueError(f"Interface '{name}' does not exist on this computer")
    c().settings.update({"bandwidth_interface": name})
    return jsonify(selected=name)


# ------------------------------------------------------------------ settings
@bp.get("/settings")
@handle_errors
def settings_get():
    k = c()
    stored = k.settings.stored()
    return jsonify(
        settings=k.settings.all(),
        pro_settings={key: stored.get(key) for key in ADVANCED_KEYS},
        simple_preset=SIMPLE_PRESET,
        advanced_keys=sorted(ADVANCED_KEYS),
        engines=list(k.settings.engines),
        engine_labels=ENGINE_LABELS,
    )


@bp.post("/reset")
@handle_errors
def reset():
    """Reset settings only (scope=settings) or everything (scope=all, requires confirm='RESET')."""
    data = body()
    scope = data.get("scope")
    if scope == "settings":
        if data.get("confirm") is not True:
            raise ValueError("Confirmation required")
        return jsonify(ok=True, scope=scope, settings=reset_settings(c()))
    if scope == "all":
        if data.get("confirm") != "RESET":
            raise ValidationError({"confirm": "Type RESET to confirm a full reset"})
        try:
            result = factory_reset(c())
        except ResetBlocked as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(ok=True, scope=scope, deleted=result["deleted"])
    raise ValueError("scope must be 'settings' or 'all'")


@bp.put("/settings")
@handle_errors
def settings_put():
    return jsonify(settings=c().settings.update(body()))


def _pkg_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


@bp.get("/health")
@handle_errors
def health():
    k = c()
    refresh = request.args.get("refresh") == "1"
    engines = {e: k.scans.health(e, refresh=refresh).to_dict() for e in k.settings.engines if e != "manual"}
    engines["manual"] = k.scans.health("manual").to_dict()
    ph = k.pinger.health()
    sched = k.scheduler.status() if k.scheduler else {"running": False, "jobs": []}
    packages = {p: _pkg_version(p) for p in ("Flask", "APScheduler", "ping3", "psutil", "scapy", "waitress", "python-dotenv")}
    return jsonify(
        engines=engines,
        pinger=ph.__dict__,
        scheduler=sched,
        packages=packages,
        platform={
            "system": platform.system(), "release": platform.release(), "python": sys.version.split()[0],
            "elevated": is_admin(), "npcap": npcap_installed() if IS_WINDOWS else None, "hostname": socket.gethostname(),
        },
        database={"path": str(current_app.config["DATABASE_PATH"])},
        demo_mode=k.demo_mode,
    )


@bp.get("/network/suggest-subnet")
@handle_errors
def suggest_subnet():
    """Suggest private subnets from this computer's own interfaces. Nothing is saved automatically."""
    out = []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family != socket.AF_INET or not a.netmask:
                continue
            try:
                iface = ipaddress.ip_interface(f"{a.address}/{a.netmask}")
            except ValueError:
                continue
            ip = iface.ip
            if ip.is_loopback or ip.is_link_local or not ip.is_private:
                continue
            net = iface.network
            if net.prefixlen < STRICT_MIN_PREFIX:  # keep suggestions small; user can widen manually
                net = ipaddress.ip_network(f"{ip}/24", strict=False)
            out.append({"interface": name, "address": str(ip), "subnet": str(net)})
    return jsonify(suggestions=out)


# ---------------------------------------------------------------------- scan
@bp.get("/scan/status")
@handle_errors
def scan_status():
    return jsonify(c().scans.status())


@bp.post("/scan/run")
@handle_errors
def scan_run():
    c().scans.start_async("manual")
    return jsonify(ok=True, message="Scan started"), 202


@bp.get("/scan/logs")
@handle_errors
def scan_logs():
    return jsonify(scans=c().scans.recent(request.args.get("limit", 20, type=int)))


@bp.post("/monitor/run")
@handle_errors
def monitor_run():
    k = c()
    if k.scheduler and k.scheduler.started:
        k.scheduler.run_now("ping")
        return jsonify(ok=True, message="Ping cycle queued"), 202
    return jsonify(ok=True, result=k.monitor.run_cycle())
