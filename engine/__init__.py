"""Pe3k — local network monitoring, security and bandwidth monitoring.

Author: heyziq05 (https://github.com/heyziq05)
"""
from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass

from flask import Flask, Response, jsonify, render_template, request

from .db import Database
from .logging_setup import configure_logging

__version__ = "1.2.1"
__author__ = "heyziq05"
__url__ = "https://github.com/heyziq05"

log = logging.getLogger("pe3k.app")


@dataclass
class Container:
    """Holds the shared services for one app instance."""

    db: Database
    settings: object
    devices: object
    alerts: object
    bandwidth: object
    bandwidth_monitor: object
    pinger: object
    monitor: object
    scans: object
    demo_mode: bool
    scheduler: object | None = None


def build_container(config) -> Container:
    from .monitoring.bandwidth import BandwidthMonitor
    from .monitoring.monitor import MonitorService
    from .monitoring.pinger import Pinger, SimulatedPinger
    from .monitoring.scan_service import ScanService
    from .services.alert_service import AlertService
    from .services.bandwidth_service import BandwidthService
    from .services.device_service import DeviceService
    from .services.settings_service import SettingsService
    from .validators import DISCOVERY_ENGINES

    demo = bool(config.DEMO_MODE)
    db = Database(config.DATABASE_PATH)
    db.init_schema()
    engines = DISCOVERY_ENGINES + (("demo",) if demo else ())
    settings = SettingsService(db, config.DEFAULT_SETTINGS, engines)
    settings.ensure_defaults()
    if not demo and settings.get("discovery_engine") == "demo":
        settings.set_raw({"discovery_engine": "manual", "auto_scan_enabled": False})
        log.warning("demo engine disabled because demo mode is off; switched to manual", extra={"event": "demo_engine_reset"})

    devices = DeviceService(db, settings)
    pinger = SimulatedPinger() if demo else Pinger(settings.get("ping_method", "auto"))
    c = Container(
        db=db,
        settings=settings,
        devices=devices,
        alerts=AlertService(db, devices),
        bandwidth=BandwidthService(db),
        bandwidth_monitor=BandwidthMonitor(db, settings, config.BANDWIDTH_SAMPLE_SECONDS, config.BANDWIDTH_PERSIST_SECONDS),
        pinger=pinger,
        monitor=MonitorService(db, settings, devices, pinger),
        scans=ScanService(db, settings, devices, demo),
        demo_mode=demo,
    )

    def on_change(keys: set[str]) -> None:
        if "ping_method" in keys and not demo:
            pinger.set_method(settings.get("ping_method", "auto"))
        if "bandwidth_interface" in keys:
            c.bandwidth_monitor.reset()
        if keys & {"discovery_engine", "nmap_path"}:
            c.scans.invalidate_health()

    settings.on_change(on_change)
    return c


def create_app(config_object=None, with_scheduler: bool = False) -> Flask:
    """Build the Flask app.

    ``with_scheduler`` starts background monitoring; only the server entry point
    (``python app.py``) passes ``True`` so CLI commands and tests never spawn jobs.
    """
    from config import Config

    cfg = config_object or Config
    configure_logging(cfg.LOG_DIR, cfg.LOG_LEVEL, testing=getattr(cfg, "TESTING", False))

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(cfg)

    container = build_container(cfg)
    app.extensions["pe3k"] = container

    if container.demo_mode:
        from .demo import seed_if_empty

        seed_if_empty(container)

    from .routes.api import bp as api_bp
    from .routes.exports import bp as exports_bp
    from .routes.pages import bp as pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(exports_bp, url_prefix="/export")

    _register_security(app)
    _register_errors(app)
    _register_context(app)

    if with_scheduler and app.config.get("START_SCHEDULER", True) and not app.config.get("TESTING"):
        from .monitoring.scheduler import start_scheduler

        container.scheduler = start_scheduler(container, cfg)

    log.info("Pe3k ready", extra={"event": "app_ready", "version": __version__, "demo": container.demo_mode})
    return app


def _register_security(app: Flask) -> None:
    password = app.config.get("AUTH_PASSWORD") or ""
    username = app.config.get("AUTH_USERNAME") or "admin"

    @app.before_request
    def guard():
        # Optional HTTP Basic auth for when Pe3k is exposed beyond localhost.
        if password:
            auth = request.authorization
            ok = (
                auth is not None
                and hmac.compare_digest((auth.username or "").encode(), username.encode())
                and hmac.compare_digest((auth.password or "").encode(), password.encode())
            )
            if not ok:
                return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="Pe3k"'})
        # CSRF defence for the JSON API: state-changing requests must carry a custom header,
        # which browsers will not send cross-origin without a CORS preflight Pe3k never approves.
        if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.headers.get("X-Pe3k-Request") != "1":
                return jsonify(error="Missing X-Pe3k-Request header"), 403
        return None

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp


def _register_errors(app: Flask) -> None:
    def wants_json() -> bool:
        return request.path.startswith("/api/") or request.path.startswith("/export/")

    @app.errorhandler(404)
    def not_found(_e):
        if wants_json():
            return jsonify(error="Not found"), 404
        return render_template("error.html", code=404, message="That page doesn't exist."), 404

    @app.errorhandler(405)
    def not_allowed(_e):
        return jsonify(error="Method not allowed"), 405

    @app.errorhandler(Exception)
    def unhandled(exc):
        from werkzeug.exceptions import HTTPException

        if isinstance(exc, HTTPException):
            return exc
        log.exception("unhandled error", extra={"event": "http_500", "path": request.path})
        if wants_json():
            return jsonify(error="Internal error — see logs/pe3k.log for details"), 500
        return render_template("error.html", code=500, message="Something went wrong. Details are in logs/pe3k.log."), 500


def _register_context(app: Flask) -> None:
    from .monitoring.discovery import ENGINE_LABELS
    from .validators import DEVICE_TYPE_LABELS

    @app.context_processor
    def inject():
        c: Container = app.extensions["pe3k"]
        return {
            "app_version": __version__,
            "demo_mode": c.demo_mode,
            "device_type_labels": DEVICE_TYPE_LABELS,
            "engine_labels": ENGINE_LABELS,
        }
