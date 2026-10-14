"""Read-side queries over ``bandwidth_logs`` (history, daily totals, exports)."""
from __future__ import annotations

from ..db import Database, rows_to_dicts
from ..timeutil import to_iso, window_start
from datetime import datetime, timezone

# history window -> bucket size in seconds
BUCKETS = {"1h": 60, "6h": 300, "24h": 900, "7d": 3600, "30d": 6 * 3600}


class BandwidthService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _iface_clause(interface: str | None, params: list) -> str:
        if interface:
            params.append(interface)
            return " AND interface = ?"
        return ""

    def history(self, window: str = "24h", interface: str | None = None) -> list[dict]:
        window = window if window in BUCKETS else "24h"
        bucket = BUCKETS[window]
        params: list = [bucket, window_start(window)]
        sql = (
            "SELECT (CAST(strftime('%s', recorded_at) AS INTEGER) / ?) AS b,"
            " SUM(bytes_recv) AS rx, SUM(bytes_sent) AS tx, SUM(interval_seconds) AS secs"
            " FROM bandwidth_logs WHERE recorded_at >= ?"
        )
        sql += self._iface_clause(interface, params) + " GROUP BY b ORDER BY b"
        with self.db.session() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            secs = r["secs"] or 1
            out.append(
                {
                    "t": to_iso(datetime.fromtimestamp(r["b"] * bucket, timezone.utc)),
                    "rx_mbps": round(r["rx"] * 8 / secs / 1e6, 3),
                    "tx_mbps": round(r["tx"] * 8 / secs / 1e6, 3),
                    "bytes_recv": int(r["rx"]),
                    "bytes_sent": int(r["tx"]),
                }
            )
        return out

    def daily_totals(self, days: int = 14, interface: str | None = None) -> list[dict]:
        days = max(1, min(int(days), 90))
        params: list = [f"-{days - 1} days"]
        sql = (
            "SELECT date(recorded_at, 'localtime') AS day, SUM(bytes_recv) AS rx, SUM(bytes_sent) AS tx,"
            " MAX(rx_mbps) AS peak_rx, MAX(tx_mbps) AS peak_tx FROM bandwidth_logs"
            " WHERE date(recorded_at, 'localtime') >= date('now', 'localtime', ?)"
        )
        sql += self._iface_clause(interface, params) + " GROUP BY day ORDER BY day"
        with self.db.session() as conn:
            return [
                {"day": r["day"], "bytes_recv": int(r["rx"] or 0), "bytes_sent": int(r["tx"] or 0),
                 "peak_rx_mbps": round(r["peak_rx"] or 0, 3), "peak_tx_mbps": round(r["peak_tx"] or 0, 3)}
                for r in conn.execute(sql, params)
            ]

    def totals(self, window: str = "24h", interface: str | None = None) -> dict:
        params: list = []
        sql = "SELECT COALESCE(SUM(bytes_recv),0) AS rx, COALESCE(SUM(bytes_sent),0) AS tx, COUNT(*) AS n FROM bandwidth_logs WHERE 1=1"
        start = window_start(window)
        if start:
            sql += " AND recorded_at >= ?"
            params.append(start)
        sql += self._iface_clause(interface, params)
        with self.db.session() as conn:
            r = conn.execute(sql, params).fetchone()
        return {"bytes_recv": int(r["rx"]), "bytes_sent": int(r["tx"]), "samples": int(r["n"])}

    def today(self, interface: str | None = None) -> dict:
        params: list = []
        sql = (
            "SELECT COALESCE(SUM(bytes_recv),0) AS rx, COALESCE(SUM(bytes_sent),0) AS tx FROM bandwidth_logs"
            " WHERE date(recorded_at, 'localtime') = date('now', 'localtime')"
        )
        sql += self._iface_clause(interface, params)
        with self.db.session() as conn:
            r = conn.execute(sql, params).fetchone()
        return {"bytes_recv": int(r["rx"]), "bytes_sent": int(r["tx"])}

    def logs(self, window: str = "7d", interface: str | None = None):
        params: list = []
        sql = "SELECT * FROM bandwidth_logs WHERE 1=1"
        start = window_start(window)
        if start:
            sql += " AND recorded_at >= ?"
            params.append(start)
        sql += self._iface_clause(interface, params) + " ORDER BY recorded_at"
        with self.db.session() as conn:
            return rows_to_dicts(conn.execute(sql, params))
