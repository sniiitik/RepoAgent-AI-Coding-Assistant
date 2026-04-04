import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402


@pytest.fixture()
def app_module(tmp_path):
    db_path = tmp_path / "test_repoagent.db"
    db.set_db_path(db_path)
    db.init_db()

    if "main" in sys.modules:
        module = importlib.reload(sys.modules["main"])
    else:
        module = importlib.import_module("main")
    return module


@pytest.fixture()
def client(app_module):
    with TestClient(app_module.app) as test_client:
        yield test_client
