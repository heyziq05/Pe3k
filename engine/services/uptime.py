"""Uptime, outage and device-status calculations.

The pure functions at the top have no database dependency, which keeps them
simple to unit-test.
"""
from __future__ import annotations

from typing import Iterable

from ..db import Database
from ..timeutil import parse_iso, window_start


# ------------------------------------------------------------ pure functions
def calculate_uptime(total_checks: int, successful_checks: int) -> float | None:
    """Uptime percentage rounded to 2 dp, or ``None`` when there is no data."""
    if total_checks is None or total_checks <= 0:
        return None
    successful = max(0, min(int(successful_checks or 0), int(total_checks)))
    return round(successful * 100.0 / total_checks, 2)


def summarize_checks(results: Iterable[bool]) -> dict:
    total = successful = 0
    for ok in results:
        total += 1
        successful += 1 if ok else 0
    return {
        "total_checks": total,
        "successful_checks": successful,
        "failed_checks": total - successful,
        "uptime_percent": calculate_uptime(total, successful),
    }


def next_status(previous_status: str, previous_failures: int, success: bool, threshold: int) -> tuple[str, int]:
    """Apply one check result to a device's state.

    A device is only marked ``offline`` after ``threshold`` consecutive failed
    checks. Fewer failures on a previously-online device mark it ``unstable``
    (still counted as up), so a single dropped ping never raises an alert.
    """
    threshold = max(1, int(threshold))
    if success:
        return "online", 0
    failures = int(previous_failures or 0) + 1
    if failures >= threshold:
        return "offline", failures
    if previous_status in ("online", "unstable"):
        return "unstable", failures
    return previous_status if previous_status in ("offline", "unknown") else "unknown", failures


def compute_outages(logs: list[dict]) -> list[dict]:
    """Derive outage periods from chronologically ordered monitor logs.

    An outage starts at the first failed check of the streak that pushed the
    device ``offline`` and ends at the next successful check.
    """
    outages: list[dict] = []
    streak_start: str | None = None
    streak_count = 0
    current: dict | None = None
    for row in logs:
        ok = bool(row["success"])
        ts = row["checked_at"]
        if ok:
            streak_start, streak_count = None, 0
            if current is not None:
                current["end"] = ts
                current["ongoing"] = False
                outages.append(current)
                current = None
            continue
        if streak_start is None:
            streak_start = ts
        streak_count += 1
        if current is None and row.get("status_after") == "offline":
            # include the failures that led up to the offline confirmation
            current = {"start": streak_start, "end": None, "ongoing": True, "failed_checks": streak_count - 1}
        if current is not None:
            current["failed_checks"] += 1
    if current is not None:
        outages.append(current)
    for o in outages:
        start, end = parse_iso(o["start"]), parse_iso(o["end"]) if o["end"] else None
        o["duration_seconds"] = int((end - start).total_seconds()) if (start and end) else None
    return outages


# ------------------------------------------------------------- DB-backed
def device_uptime(db: Database, device_id: int, window: str = "24h") -> dict:
    start = window_start(window)
    sql = (
        "SELECT COUNT(*) AS total, COALESCE(SUM(success), 0) AS ok, AVG(CASE WHEN success = 1 THEN latency_ms END) AS avg_lat,"
        " MIN(CASE WHEN success = 1 THEN latency_ms END) AS min_lat, MAX(CASE WHEN success = 1 THEN latency_ms END) AS max_lat"
        " FROM monitor_logs WHERE device_id = ?"
    )
    params: list = [device_id]
    if start:
        sql += " AND checked_at >= ?"
        params.append(start)
    with db.session() as conn:
        row = conn.execute(sql, params).fetchone()
    total, ok = int(row["total"]), int(row["ok"])
    return {
        "window": window,
        "total_checks": total,
        "successful_checks": ok,
        "failed_checks": total - ok,
        "uptime_percent": calculate_uptime(total, ok),
        "avg_latency_ms": round(row["avg_lat"], 2) if row["avg_lat"] is not None else None,
        "min_latency_ms": round(row["min_lat"], 2) if row["min_lat"] is not None else None,
        "max_latency_ms": round(row["max_lat"], 2) if row["max_lat"] is not None else None,
    }


def uptime_summary(db: Database, window: str = "24h") -> list[dict]:
    start = window_start(window)
    join_cond = "l.device_id = d.id" + (" AND l.checked_at >= ?" if start else "")
    sql = (
        "SELECT d.id, d.name, d.ip_address, d.mac_address, d.device_type, d.status, d.last_seen,"
        " COUNT(l.id) AS total, COALESCE(SUM(l.success), 0) AS ok,"
        " AVG(CASE WHEN l.success = 1 THEN l.latency_ms END) AS avg_lat"
        f" FROM devices d LEFT JOIN monitor_logs l ON {join_cond}"
        " GROUP BY d.id ORDER BY d.name COLLATE NOCASE"
    )
    with db.session() as conn:
        rows = conn.execute(sql, [start] if start else []).fetchall()
    out = []
    for r in rows:
        total, ok = int(r["total"]), int(r["ok"])
        out.append(
            {
                "device_id": r["id"],
                "name": r["name"],
                "ip_address": r["ip_address"],
                "mac_address": r["mac_address"],
                "device_type": r["device_type"],
                "status": r["status"],
                "last_seen": r["last_seen"],
                "total_checks": total,
                "successful_checks": ok,
                "failed_checks": total - ok,
                "uptime_percent": calculate_uptime(total, ok),
                "avg_latency_ms": round(r["avg_lat"], 2) if r["avg_lat"] is not None else None,
            }
        )
    return out


def device_outages(db: Database, device_id: int, window: str = "7d") -> list[dict]:
    start = window_start(window)
    sql = "SELECT checked_at, success, status_after FROM monitor_logs WHERE device_id = ?"
    params: list = [device_id]
    if start:
        sql += " AND checked_at >= ?"
        params.append(start)
    sql += " ORDER BY checked_at ASC, id ASC"
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute(sql, params)]
    return list(reversed(compute_outages(rows)))
