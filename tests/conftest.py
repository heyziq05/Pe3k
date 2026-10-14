import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import TestConfig  # noqa: E402
from engine import create_app  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    class Cfg(TestConfig):
        DATA_DIR = tmp_path
        DATABASE_PATH = tmp_path / "test.sqlite3"
        LOG_DIR = tmp_path / "logs"
        DEFAULT_SETTINGS = {**TestConfig.DEFAULT_SETTINGS, "discovery_engine": "manual", "authorized_subnet": "",
                            "auto_scan_enabled": False, "scan_authorized_ack": False, "strict_scope": True,
                            "settings_mode": "pro"}

    return create_app(Cfg)


@pytest.fixture()
def c(app):
    """The service container."""
    return app.extensions["pe3k"]


@pytest.fixture()
def client(app):
    return app.test_client()


HDR = {"X-Pe3k-Request": "1"}
