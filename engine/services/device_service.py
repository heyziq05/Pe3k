"""Trusted-device CRUD with validation and uniqueness checks."""
from __future__ import annotations

import logging
import sqlite3

from ..db import Database, row_to_dict, rows_to_dicts
from ..timeutil import now_iso
from ..validators import DEVICE_TYPES, ValidationError, validate_device_payload

log = logging.getLogger("pe3k.devices")

DEVICE_COLUMNS = (
    "id, name, ip_address, mac_address, device_type, trusted, monitoring_enabled, status, last_latency_ms,"
    " consecutive_failures, last_checked, last_seen, notes, date_added, updated_at"
)
STATUSES = ("online", "unstable", "offline", "unknown")


class NotFound(LookupError):
    pass


def _conflicts(conn: sqlite3.Connection, data: dict, exclude_id: int | None = None) -> dict[str, str]:
    errors: dict[str, str] = {}
    for field, label in (("ip_address", "IP address"), ("mac_address", "MAC address")):
        value = data.get(field)
        if not value:
            continue
        sql = f"SELECT id, name FROM devices WHERE {field} = ?"  # field is from a fixed tuple
        params: list = [value]
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        row = conn.execute(sql, params).fetchone()
        if row:
            errors[field] = f"{label} {value} is already used by '{row['name']}'"
    return errors


class DeviceService:
    def __init__(self, db: Database, settings):
        self.db = db
        self.settings = settings

    def _strict(self) -> bool:
        return bool(self.settings.get("strict_scope", True))

    # ------------------------------------------------------------ queries
    def list(self, search: str = "", status: str = "", device_type: str = "", trusted: str = "") -> list[dict]:
        sql = f"SELECT {DEVICE_COLUMNS} FROM devices WHERE 1=1"
        params: list = []
        if search:
            like = f"%{search.strip()}%"
            sql += " AND (name LIKE ? OR ip_address LIKE ? OR IFNULL(mac_address,'') LIKE ? OR notes LIKE ?)"
            params += [like, like, like, like]
        if status in STATUSES:
            sql += " AND status = ?"
            params.append(status)
        if device_type in DEVICE_TYPES:
            sql += " AND device_type = ?"
            params.append(device_type)
        if trusted in ("0", "1"):
            sql += " AND trusted = ?"
            params.append(int(trusted))
        sql += " ORDER BY CASE status WHEN 'offline' THEN 0 WHEN 'unstable' THEN 1 WHEN 'unknown' THEN 2 ELSE 3 END, name COLLATE NOCASE"
        with self.db.session() as conn:
            return rows_to_dicts(conn.execute(sql, params))

    def get(self, device_id: int) -> dict:
        with self.db.session() as conn:
            row = conn.execute(f"SELECT {DEVICE_COLUMNS} FROM devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            raise NotFound(f"Device {device_id} not found")
        return dict(row)

    def monitored(self) -> list[dict]:
        with self.db.session() as conn:
            return rows_to_dicts(
                conn.execute(f"SELECT {DEVICE_COLUMNS} FROM devices WHERE monitoring_enabled = 1 ORDER BY id")
            )

    def counts(self) -> dict:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total,"
                " SUM(status = 'online') AS online, SUM(status = 'unstable') AS unstable,"
                " SUM(status = 'offline') AS offline, SUM(status = 'unknown') AS unknown,"
                " SUM(trusted = 1) AS trusted FROM devices"
            ).fetchone()
        return {k: int(row[k] or 0) for k in row.keys()}

    # ------------------------------------------------------------ commands
    def create(self, payload: dict, conn: sqlite3.Connection | None = None) -> dict:
        data = validate_device_payload(payload, self._strict())
        if conn is not None:
            return self._insert(conn, data)
        with self.db.transaction() as tx:
            return self._insert(tx, data)

    def _insert(self, conn: sqlite3.Connection, data: dict) -> dict:
        errors = _conflicts(conn, data)
        if errors:
            raise ValidationError(errors)
        now = now_iso()
        cur = conn.execute(
            "INSERT INTO devices(name, ip_address, mac_address, device_type, trusted, monitoring_enabled,"
            " notes, date_added, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["name"], data["ip_address"], data.get("mac_address"), data.get("device_type", "other"),
                data.get("trusted", 1), data.get("monitoring_enabled", 1), data.get("notes", ""), now, now,
            ),
        )
        device_id = cur.lastrowid
        if data.get("trusted", 1) and data.get("mac_address"):
            # Trusting a MAC closes any open unknown-device alerts for it.
            conn.execute(
                "UPDATE alerts SET status = 'trusted', resolved_at = ?, resolution = 'Added to trusted devices',"
                " device_id = ? WHERE alert_type = 'unknown_device' AND mac_address = ? AND status IN ('open','ignored')",
                (now, device_id, data["mac_address"]),
            )
        log.info("device created", extra={"event": "device_created", "device_id": device_id, "ip": data["ip_address"]})
        return dict(conn.execute(f"SELECT {DEVICE_COLUMNS} FROM devices WHERE id = ?", (device_id,)).fetchone())

    def update(self, device_id: int, payload: dict) -> dict:
        data = validate_device_payload(payload, self._strict(), partial=True)
        if not data:
            raise ValidationError({"_": "Nothing to update"})
        with self.db.transaction() as conn:
            existing = conn.execute("SELECT id, ip_address FROM devices WHERE id = ?", (device_id,)).fetchone()
            if existing is None:
                raise NotFound(f"Device {device_id} not found")
            errors = _conflicts(conn, data, exclude_id=device_id)
            if errors:
                raise ValidationError(errors)
            if "ip_address" in data and data["ip_address"] != existing["ip_address"]:
                # A new address means previous status no longer applies.
                data.update(status="unknown", consecutive_failures=0, last_latency_ms=None)
            data["updated_at"] = now_iso()
            assignments = ", ".join(f"{k} = ?" for k in data)  # keys come from the validator whitelist
            conn.execute(f"UPDATE devices SET {assignments} WHERE id = ?", [*data.values(), device_id])
            if data.get("trusted") == 1:
                mac = conn.execute("SELECT mac_address FROM devices WHERE id = ?", (device_id,)).fetchone()[0]
                if mac:
                    conn.execute(
                        "UPDATE alerts SET status = 'trusted', resolved_at = ?, resolution = 'Device trusted'"
                        " WHERE alert_type = 'unknown_device' AND mac_address = ? AND status IN ('open','ignored')",
                        (now_iso(), mac),
                    )
            row = conn.execute(f"SELECT {DEVICE_COLUMNS} FROM devices WHERE id = ?", (device_id,)).fetchone()
        log.info("device updated", extra={"event": "device_updated", "device_id": device_id})
        return dict(row)

    def delete(self, device_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE alerts SET status = 'resolved', resolved_at = ?, resolution = 'Device removed'"
                " WHERE alert_type = 'device_offline' AND device_id = ? AND status IN ('open','ignored')",
                (now_iso(), device_id),
            )
            cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            if cur.rowcount == 0:
                raise NotFound(f"Device {device_id} not found")
        log.info("device deleted", extra={"event": "device_deleted", "device_id": device_id})

    def set_trusted(self, device_id: int, trusted: bool) -> dict:
        return self.update(device_id, {"trusted": trusted})

    def find_by_mac(self, mac: str) -> dict | None:
        with self.db.session() as conn:
            return row_to_dict(conn.execute(f"SELECT {DEVICE_COLUMNS} FROM devices WHERE mac_address = ?", (mac,)).fetchone())
