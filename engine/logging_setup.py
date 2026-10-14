"""Structured logging: JSON lines to ``logs/pe3k.log`` and readable console output.

Usage::

    log.info("ping finished", extra={"event": "ping", "device_id": 3, "latency_ms": 2.1})

Any ``extra`` keys are emitted as top-level JSON fields.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path

_STD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}
_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS and not k.startswith("_")}
        if extras:
            base += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def configure_logging(log_dir: Path, level: str = "INFO", testing: bool = False) -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("pe3k")
    root.setLevel(getattr(logging, level, logging.INFO))
    root.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(ConsoleFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root.addHandler(console)

    if not testing:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_dir / "pe3k.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
            )
            fh.setFormatter(JsonFormatter())
            root.addHandler(fh)
        except OSError as exc:  # pragma: no cover - read-only FS etc.
            root.warning("file logging disabled: %s", exc)

    # Quieten noisy libraries
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
    _configured = True
