"""In-app alerts with de-duplication.

De-duplication rules
--------------------
* Each alert has a ``dedup_key`` (``unknown:<MAC>``, ``unknown-ip:<IP>`` when the
  scanner cannot see MACs, or ``offline:<device id>``).
* While an alert with the same key is *active* (``open`` or ``ignored``), new
  detections only bump ``last_seen`` / ``occurrences`` – no new alert is created.
  A partial unique index in the schema enforces this at the database level.
* ``ignored`` alerts keep suppressing the same device until they are resolved.
* ``resolved`` means "dealt with". If the same unknown device is detected again
  later a new alert is opened.
"""
from __future__ import annotations

import logging
import sqlite3

from ..db import Database, row_to_dict, rows_to_dicts
from ..timeutil import now_iso
from .device_service import NotFound

log = logging.getLogger("pe3k.alerts")

ALERT_TYPES = ("unknown_device", "device_offline")
ALERT_STATUSES = ("open", "ignored", "resolved", "trusted")
ACTIVE = ("open", "ignored")


def unknown_device_key(mac: str | None, ip: str) -> str:
    return f"unknown:{mac}" if mac else f"unknown-ip:{ip}"


def offline_key(device_id: int) -> str:
    return f"offline:{device_id}"


def _active_by_key(conn: sqlite3.Connection, key: str):
    return conn.execute(
        "SELECT * FROM alerts WHERE dedup_key = ? AND status IN ('open','ignored') ORDER BY id DESC LIMIT 1", (key,)
    ).fetchone()


def upsert_unknown_device(
    conn: sqlite3.Connection, *, ip: str, mac: str | None, engine: str,
    hostname: str | None = None, vendor: str | None = None, seen_at: str | None = None,
) -> tuple[dict, bool]:
    """Record an unknown-device detection. Returns ``(alert, created)``."""
    ts = seen_at or now_iso()
    key = unknown_device_key(mac, ip)
    existing = _active_by_key(conn, key)
    if existing is not None:
        conn.execute(
            "UPDATE alerts SET last_seen = ?, occurrences = occurrences + 1, ip_address = ?, engine = ?,"
            " hostname = COALESCE(?, hostname), vendor = COALESCE(?, vendor) WHERE id = ?",
            (ts, ip, engine, hostname, vendor, existing["id"]),
        )
        return dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (existing["id"],)).fetchone()), False
    label = mac or "MAC unavailable"
    message = f"Unknown device {ip} ({label}) detected on the network"
    cur = conn.execute(
        "INSERT INTO alerts(alert_type, severity, status, dedup_key, ip_address, mac_address, hostname, vendor,"
        " engine, message, first_seen, last_seen) VALUES ('unknown_device', 'warning', 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, ip, mac, hostname, vendor, engine, message, ts, ts),
    )
    log.warning("unknown device", extra={"event": "unknown_device", "ip": ip, "mac": mac or "", "engine": engine})
    return dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone()), True


def upsert_offline(conn: sqlite3.Connection, device: dict, seen_at: str | None = None) -> tuple[dict, bool]:
    ts = seen_at or now_iso()
    key = offline_key(device["id"])
    existing = _active_by_key(conn, key)
    if existing is not None:
        conn.execute("UPDATE alerts SET last_seen = ?, occurrences = occurrences + 1 WHERE id = ?", (ts, existing["id"]))
        return dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (existing["id"],)).fetchone()), False
    cur = conn.execute(
        "INSERT INTO alerts(alert_type, severity, status, dedup_key, device_id, ip_address, mac_address, engine,"
        " message, first_seen, last_seen) VALUES ('device_offline', 'critical', 'open', ?, ?, ?, ?, 'ping', ?, ?, ?)",
        (key, device["id"], device["ip_address"], device.get("mac_address"),
         f"{device['name']} ({device['ip_address']}) is offline", ts, ts),
    )
    log.warning("device offline", extra={"event": "device_offline", "device_id": device["id"], "ip": device["ip_address"]})
    return dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone()), True


def touch_offline(conn: sqlite3.Connection, device_id: int, ts: str | None = None) -> None:
    """Refresh ``last_seen`` on an active offline alert without creating a new one."""
    conn.execute(
        "UPDATE alerts SET last_seen = ?, occurrences = occurrences + 1 WHERE dedup_key = ? AND status IN ('open','ignored')",
        (ts or now_iso(), offline_key(device_id)),
    )


def auto_resolve_offline(conn: sqlite3.Connection, device_id: int, ts: str | None = None) -> int:
    cur = conn.execute(
        "UPDATE alerts SET status = 'resolved', resolved_at = ?, resolution = 'Device came back online'"
        " WHERE dedup_key = ? AND status IN ('open','ignored')",
        (ts or now_iso(), offline_key(device_id)),
    )
    return cur.rowcount


class AlertService:
    def __init__(self, db: Database, devices):
        self.db = db
        self.devices = devices

    def list(self, status: str = "open", alert_type: str = "", limit: int = 500,
             since: str | None = None, until: str | None = None) -> list[dict]:
        """List alerts. ``since``/``until`` (UTC ISO) keep alerts that were active in that period:
        last seen at or after ``since`` and first seen at or before ``until``."""
        sql = "SELECT a.*, d.name AS device_name FROM alerts a LEFT JOIN devices d ON d.id = a.device_id WHERE 1=1"
        params: list = []
        if since:
            sql += " AND a.last_seen >= ?"
            params.append(since)
        if until:
            sql += " AND a.first_seen <= ?"
            params.append(until)
        if status in ALERT_STATUSES:
            sql += " AND a.status = ?"
            params.append(status)
        if alert_type in ALERT_TYPES:
            sql += " AND a.alert_type = ?"
            params.append(alert_type)
        sql += " ORDER BY a.last_seen DESC, a.id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 50000)))
        with self.db.session() as conn:
            return rows_to_dicts(conn.execute(sql, params))

    def get(self, alert_id: int) -> dict:
        with self.db.session() as conn:
            row = row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
        if row is None:
            raise NotFound(f"Alert {alert_id} not found")
        return row

    def counts(self) -> dict:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT SUM(status = 'open') AS open,"
                " SUM(status = 'open' AND alert_type = 'unknown_device') AS unknown_open,"
                " SUM(status = 'open' AND alert_type = 'device_offline') AS offline_open,"
                " SUM(status = 'ignored') AS ignored, SUM(status IN ('resolved','trusted')) AS closed FROM alerts"
            ).fetchone()
        return {k: int(row[k] or 0) for k in row.keys()}

    def set_status(self, alert_id: int, action: str) -> dict:
        now = now_iso()
        with self.db.transaction() as conn:
            alert = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if alert is None:
                raise NotFound(f"Alert {alert_id} not found")
            if action == "ignore":
                conn.execute("UPDATE alerts SET status = 'ignored', resolution = 'Ignored by user' WHERE id = ?", (alert_id,))
            elif action == "resolve":
                conn.execute(
                    "UPDATE alerts SET status = 'resolved', resolved_at = ?, resolution = 'Resolved by user' WHERE id = ?",
                    (now, alert_id),
                )
            elif action == "reopen":
                if alert["status"] in ACTIVE:
                    pass
                elif _active_by_key(conn, alert["dedup_key"]) is not None:
                    raise ValueError("A newer alert for this device is already active")
                else:
                    conn.execute(
                        "UPDATE alerts SET status = 'open', resolved_at = NULL, resolution = NULL WHERE id = ?", (alert_id,)
                    )
            else:
                raise ValueError("Unknown action")
            row = dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
        log.info("alert updated", extra={"event": "alert_" + action, "alert_id": alert_id})
        return row

    def trust(self, alert_id: int, payload: dict) -> dict:
        """Create a trusted device from an unknown-device alert and close the alert atomically."""
        with self.db.transaction() as conn:
            alert = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if alert is None:
                raise NotFound(f"Alert {alert_id} not found")
            if alert["alert_type"] != "unknown_device":
                raise ValueError("Only unknown-device alerts can be trusted")
            device_payload = {
                "name": payload.get("name") or alert["hostname"] or f"Device {alert['ip_address']}",
                "ip_address": payload.get("ip_address") or alert["ip_address"],
                "mac_address": payload.get("mac_address", alert["mac_address"]),
                "device_type": payload.get("device_type", "other"),
                "notes": payload.get("notes", f"Trusted from alert #{alert_id}"),
                "trusted": True,
                "monitoring_enabled": payload.get("monitoring_enabled", True),
            }
            device = self.devices.create(device_payload, conn=conn)
            conn.execute(
                "UPDATE alerts SET status = 'trusted', resolved_at = ?, resolution = 'Added to trusted devices',"
                " device_id = ? WHERE id = ?",
                (now_iso(), device["id"], alert_id),
            )
        log.info("alert trusted", extra={"event": "alert_trusted", "alert_id": alert_id, "device_id": device["id"]})
        return device
