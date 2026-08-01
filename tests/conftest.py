import sys
from pathlib import Path

# Two import conventions coexist: the web app runs with src/ on the path
# (`from database.queries import ...`), scrapers run from the repo root
# (`from scrapers.pipelines import ...`). Tests need both.
ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT / "src"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import pytest
from unittest.mock import MagicMock
import app as _app_module
from app import app as flask_app


@pytest.fixture(autouse=True)
def _block_feedback_db_writes(monkeypatch):
    """Prevent any test from accidentally writing to the real recommendation_feedback table.

    conftest.py loads the real .env, so a missed monkeypatch in a test would otherwise
    hit the production DB. This fixture is the safety net.
    """
    monkeypatch.setattr(_app_module, "insert_recommendation_feedback", MagicMock())


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
