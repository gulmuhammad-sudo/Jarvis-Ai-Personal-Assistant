"""Test setup: every test run uses a throw-away data folder, never your real settings, memories or keys.

Run:   .venv\\Scripts\\python -m pytest tests
Tests that call real AI services are marked `network` and skipped unless PA_TEST_NETWORK=1.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Must happen before anything imports jarvis: jarvis.config picks its data folder at import time.
_DATA = Path(tempfile.mkdtemp(prefix="pa-tests-"))
os.environ["JARVIS_DATA_DIR"] = str(_DATA)
os.environ["JARVIS_HANDSFREE"] = "off"            # never open the microphone...
os.environ["JARVIS_NO_MIC"] = "1"                 # ...not even the start-up check for a working mic
os.environ.setdefault("JARVIS_HUD_PORT", "8779")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))


def pytest_configure(config):
    config.addinivalue_line("markers", "network: calls real online services (set PA_TEST_NETWORK=1 to run)")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("PA_TEST_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="online test: set PA_TEST_NETWORK=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def data_dir() -> Path:
    return _DATA


@pytest.fixture(autouse=True)
def _no_real_env_file(monkeypatch, tmp_path):
    """Nothing a test does may write the real .env (one old test once did)."""
    from jarvis import config
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")


@pytest.fixture(autouse=True)
def _no_reminders_from_other_tests(monkeypatch):
    """A Hub made in one test keeps its reminder thread; with the next test's made-up data it took that test's reminders first."""
    from jarvis import schedule
    monkeypatch.setattr(schedule.Scheduler, "_loop", lambda self: None)
