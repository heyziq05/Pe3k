"""Typed key/value settings stored in the ``settings`` table (values are JSON).

Settings modes
--------------
* **Simple** (default): the advanced keys in :data:`SIMPLE_PRESET` are fixed to
  recommended values and cannot be changed. The user only picks the scanner, the
  authorized subnet, the authorization checkbox and whether scans run automatically.
* **Pro**: every setting can be customised.

The user's own Pro values stay stored while Simple mode is active, so switching
back to Pro restores them. :meth:`SettingsService.all` always returns the
*effective* settings (presets applied in Simple mode).
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

from ..db import Database
from ..timeutil import now_iso
from ..validators import DISCOVERY_ENGINES, ValidationError, validate_settings_payload

log = logging.getLogger("pe3k.settings")

MODES = ("simple", "pro")

# Recommended values used (and locked) in Simple mode.
SIMPLE_PRESET: dict[str, Any] = {
    "scan_interval_seconds": 300,
    "scan_timeout_seconds": 60,
    "ping_interval_seconds": 45,
    "ping_timeout_seconds": 1.5,
    "ping_retries": 2,
    "failure_threshold": 3,
    "ping_method": "auto",
    "strict_scope": True,
    "offline_alerts_enabled": True,
    "use_arp_cache": True,
    "phone_tuning_enabled": True,
    "phone_ping_timeout_seconds": 3.0,
    "phone_ping_retries": 4,
    "phone_retry_delay_seconds": 0.75,
    "phone_failure_threshold": 6,
}
ADVANCED_KEYS = frozenset(SIMPLE_PRESET)
LOCKED_MESSAGE = "Locked in Simple mode (recommended preset). Switch to Pro mode to customise it."


class SettingsService:
    def __init__(self, db: Database, defaults: dict[str, Any], engines: tuple[str, ...] = DISCOVERY_ENGINES):
        self.db = db
        self.defaults = dict(defaults)
        self.defaults.setdefault("settings_mode", "simple")
        self.engines = engines
        self._listeners: list[Callable[[set[str]], None]] = []
        self._lock = threading.RLock()

    def ensure_defaults(self) -> None:
        """Insert defaults for keys that are missing (never overwrites user choices)."""
        with self.db.transaction() as conn:
            for key, value in self.defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value), now_iso()),
                )

    # ------------------------------------------------------------- reading
    def stored(self) -> dict[str, Any]:
        """Defaults merged with what the user saved (Pro values, even while in Simple mode)."""
        data = dict(self.defaults)
        with self.db.session() as conn:
            for row in conn.execute("SELECT key, value FROM settings"):
                try:
                    data[row["key"]] = json.loads(row["value"])
                except (TypeError, ValueError):
                    log.warning("ignoring corrupt setting", extra={"event": "setting_corrupt", "key": row["key"]})
        if data.get("settings_mode") not in MODES:
            data["settings_mode"] = "simple"
        return data

    @staticmethod
    def effective(stored: dict[str, Any]) -> dict[str, Any]:
        data = dict(stored)
        if data.get("settings_mode") == "simple":
            data.update(SIMPLE_PRESET)
        return data

    def all(self) -> dict[str, Any]:
        """Effective settings: presets applied when Simple mode is on."""
        return self.effective(self.stored())

    def get(self, key: str, default: Any = None) -> Any:
        return self.all().get(key, self.defaults.get(key, default))

    # ------------------------------------------------------------- writing
    def set_raw(self, values: dict[str, Any]) -> None:
        """Write already-validated values (used by seeding and internal code)."""
        with self.db.transaction() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (key, json.dumps(value), now_iso()),
                )

    def update(self, payload: dict) -> dict[str, Any]:
        """Validate and persist a partial settings update; notifies listeners of changed effective keys."""
        if not isinstance(payload, dict):
            raise ValidationError({"_": "Expected a JSON object"})
        with self._lock:
            stored = self.stored()
            before = self.effective(stored)
            payload = dict(payload)
            mode = str(payload.pop("settings_mode", stored["settings_mode"])).strip().lower()
            if mode not in MODES:
                raise ValidationError({"settings_mode": "Choose Simple or Pro mode"})
            if mode == "simple":
                locked = {k: LOCKED_MESSAGE for k in payload if k in ADVANCED_KEYS}
                if locked:
                    raise ValidationError(locked)
                current = {**stored, **SIMPLE_PRESET}
            else:
                current = stored
            cleaned = validate_settings_payload(payload, current, self.engines)
            cleaned["settings_mode"] = mode
            to_write = {k: v for k, v in cleaned.items() if stored.get(k) != v}
            if to_write:
                self.set_raw(to_write)
            after = self.all()
            changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
            if changed:
                log.info("settings updated", extra={"event": "settings_updated", "mode": mode,
                                                    "keys": ",".join(sorted(changed))})
        self._notify(changed)
        return after

    def reset(self) -> dict[str, Any]:
        """Restore every setting to its default (devices and history are untouched)."""
        with self._lock:
            before = self.all()
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM settings")
            self.ensure_defaults()
            after = self.all()
        log.warning("settings reset to defaults", extra={"event": "settings_reset"})
        self._notify({k for k in set(before) | set(after) if before.get(k) != after.get(k)} or set(after))
        return after

    # ----------------------------------------------------------- listeners
    def on_change(self, callback: Callable[[set[str]], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, changed: set[str]) -> None:
        if not changed:
            return
        for listener in list(self._listeners):
            try:
                listener(changed)
            except Exception:  # a listener must never break saving settings
                log.exception("settings listener failed", extra={"event": "settings_listener_error"})
