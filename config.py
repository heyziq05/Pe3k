"""Pe3k configuration.

Author: heyziq05 (https://github.com/heyziq05)

Every value can be overridden with an environment variable (or a ``.env`` file
in the project root). Nothing network-specific is hard-coded: the authorized
subnet, executable paths and credentials all come from the environment or from
the Settings page (which is stored in SQLite).
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:  # python-dotenv is optional but recommended
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:  # pragma: no cover - dotenv missing is fine
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    # --- Flask -----------------------------------------------------------
    SECRET_KEY = os.environ.get("PE3K_SECRET_KEY") or os.urandom(32).hex()
    HOST = os.environ.get("PE3K_HOST", "127.0.0.1")
    PORT = _env_int("PE3K_PORT", 5000)
    DEBUG = _env_bool("PE3K_DEBUG", False)
    JSON_SORT_KEYS = False

    # Optional HTTP Basic auth. Leave empty to disable (fine when bound to 127.0.0.1).
    AUTH_USERNAME = os.environ.get("PE3K_AUTH_USERNAME", "admin")
    AUTH_PASSWORD = os.environ.get("PE3K_AUTH_PASSWORD", "")

    # --- Storage ---------------------------------------------------------
    DATA_DIR = Path(os.environ.get("PE3K_DATA_DIR", BASE_DIR / "data"))
    DATABASE_PATH = Path(os.environ.get("PE3K_DATABASE", DATA_DIR / "pe3k.sqlite3"))
    LOG_DIR = Path(os.environ.get("PE3K_LOG_DIR", BASE_DIR / "logs"))
    LOG_LEVEL = os.environ.get("PE3K_LOG_LEVEL", "INFO").upper()

    # --- Behaviour -------------------------------------------------------
    START_SCHEDULER = _env_bool("PE3K_START_SCHEDULER", True)
    DEMO_MODE = _env_bool("PE3K_DEMO_MODE", False)

    # Retention (days) for high-volume tables; pruned once a day.
    MONITOR_RETENTION_DAYS = _env_int("PE3K_MONITOR_RETENTION_DAYS", 30)
    BANDWIDTH_RETENTION_DAYS = _env_int("PE3K_BANDWIDTH_RETENTION_DAYS", 90)
    SCAN_LOG_RETENTION_DAYS = _env_int("PE3K_SCAN_LOG_RETENTION_DAYS", 30)

    # Bandwidth sampling: live sample interval and how often a row is persisted.
    BANDWIDTH_SAMPLE_SECONDS = max(1, _env_int("PE3K_BANDWIDTH_SAMPLE_SECONDS", 5))
    BANDWIDTH_PERSIST_SECONDS = max(10, _env_int("PE3K_BANDWIDTH_PERSIST_SECONDS", 60))

    # Initial values for the Settings page (only used to seed an empty DB).
    DEFAULT_SETTINGS = {
        # simple = recommended presets, advanced fields locked; pro = everything customisable
        "settings_mode": os.environ.get("PE3K_SETTINGS_MODE", "simple"),
        "discovery_engine": os.environ.get("PE3K_DISCOVERY_ENGINE", "manual"),
        "authorized_subnet": os.environ.get("PE3K_AUTHORIZED_SUBNET", ""),
        "nmap_path": os.environ.get("PE3K_NMAP_PATH", ""),
        "scan_interval_seconds": _env_int("PE3K_SCAN_INTERVAL_SECONDS", 300),
        "scan_timeout_seconds": _env_int("PE3K_SCAN_TIMEOUT_SECONDS", 60),
        "ping_interval_seconds": _env_int("PE3K_PING_INTERVAL_SECONDS", 45),
        "ping_timeout_seconds": float(os.environ.get("PE3K_PING_TIMEOUT_SECONDS", 1.5)),
        "ping_retries": _env_int("PE3K_PING_RETRIES", 2),
        "failure_threshold": _env_int("PE3K_FAILURE_THRESHOLD", 3),
        "ping_method": os.environ.get("PE3K_PING_METHOD", "auto"),
        "bandwidth_interface": os.environ.get("PE3K_BANDWIDTH_INTERFACE", "all"),
        "auto_scan_enabled": _env_bool("PE3K_AUTO_SCAN", False),
        "scan_authorized_ack": False,
        "strict_scope": _env_bool("PE3K_STRICT_SCOPE", True),
        "offline_alerts_enabled": True,
        # Merge the OS ARP cache into Nmap/Scapy scans (catches devices that sleep during a scan).
        "use_arp_cache": _env_bool("PE3K_USE_ARP_CACHE", True),
        # Gentler ping profile for phones/tablets (they power-save Wi-Fi when locked).
        "phone_tuning_enabled": True,
        "phone_ping_timeout_seconds": float(os.environ.get("PE3K_PHONE_PING_TIMEOUT_SECONDS", 3.0)),
        "phone_ping_retries": _env_int("PE3K_PHONE_PING_RETRIES", 4),
        "phone_retry_delay_seconds": float(os.environ.get("PE3K_PHONE_RETRY_DELAY_SECONDS", 0.75)),
        "phone_failure_threshold": _env_int("PE3K_PHONE_FAILURE_THRESHOLD", 6),
    }


class TestConfig(Config):
    TESTING = True
    START_SCHEDULER = False
    DEMO_MODE = False
    SECRET_KEY = "test"
    AUTH_PASSWORD = ""
