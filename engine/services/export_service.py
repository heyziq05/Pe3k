"""CSV exports built with Python's ``csv`` module.

Cells that start with ``= + - @`` (or tab/CR) are prefixed with ``'`` so a CSV
opened in Excel cannot execute formulas injected via device names, hostnames
or other user/network-controlled text.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Iterable, Sequence

from ..timeutil import utcnow

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def safe_cell(value) -> object:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text.startswith(_DANGEROUS) and not _NUMERIC.match(text):
        return "'" + text
    return text


def to_csv(columns: Sequence[tuple[str, str]], rows: Iterable[dict]) -> str:
    """``columns`` is a list of ``(key, header)`` pairs."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow([safe_cell(row.get(key)) for key, _ in columns])
    return "﻿" + buf.getvalue()  # BOM so Excel detects UTF-8


def filename(prefix: str) -> str:
    return f"pe3k-{prefix}-{utcnow().strftime('%Y%m%d-%H%M%S')}.csv"


DEVICE_COLUMNS = [
    ("id", "ID"), ("name", "Name"), ("ip_address", "IP address"), ("mac_address", "MAC address"),
    ("device_type", "Device type"), ("trusted", "Trusted"), ("monitoring_enabled", "Monitoring enabled"),
    ("status", "Current status"), ("last_latency_ms", "Last latency (ms)"),
    ("consecutive_failures", "Consecutive failures"), ("last_checked", "Last checked (UTC)"),
    ("last_seen", "Last seen (UTC)"), ("date_added", "Date added (UTC)"), ("notes", "Notes"),
]
HISTORY_COLUMNS = [
    ("checked_at", "Checked at (UTC)"), ("success", "Success"), ("latency_ms", "Latency (ms)"),
    ("status_after", "Status after check"), ("attempts", "Attempts"), ("error", "Error"),
]
ALERT_COLUMNS = [
    ("id", "ID"), ("alert_type", "Type"), ("severity", "Severity"), ("status", "Status"),
    ("ip_address", "IP address"), ("mac_address", "MAC address"), ("hostname", "Hostname"),
    ("device_name", "Device"), ("engine", "Discovery engine"), ("message", "Message"),
    ("occurrences", "Occurrences"), ("first_seen", "First seen (UTC)"), ("last_seen", "Last seen (UTC)"),
    ("resolved_at", "Resolved at (UTC)"), ("resolution", "Resolution"),
]
BANDWIDTH_COLUMNS = [
    ("recorded_at", "Recorded at (UTC)"), ("interface", "Interface"), ("interval_seconds", "Interval (s)"),
    ("bytes_recv", "Bytes received"), ("bytes_sent", "Bytes sent"), ("rx_mbps", "Download (Mbps)"),
    ("tx_mbps", "Upload (Mbps)"),
]
UPTIME_COLUMNS = [
    ("device_id", "Device ID"), ("name", "Name"), ("ip_address", "IP address"), ("mac_address", "MAC address"),
    ("device_type", "Device type"), ("status", "Current status"), ("total_checks", "Total checks"),
    ("successful_checks", "Successful checks"), ("failed_checks", "Failed checks"),
    ("uptime_percent", "Uptime %"), ("avg_latency_ms", "Avg latency (ms)"), ("last_seen", "Last seen (UTC)"),
]
