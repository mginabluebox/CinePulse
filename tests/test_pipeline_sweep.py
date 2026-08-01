"""Unit tests for the stale-showtime sweep in CinemaScraperPipeline.

Mocks the engine/connection/cursor so no live Postgres is required (per the
"lightweight unit tests that mock engines/cursors" convention in AGENTS.md).
"""
from unittest.mock import MagicMock

import psycopg2
import pytest

from scrapers.pipelines import CinemaScraperPipeline


@pytest.fixture
def pipeline(monkeypatch):
    """A pipeline wired to a mock connection/cursor via a patched get_engine()."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    engine = MagicMock()
    engine.raw_connection.return_value = conn
    monkeypatch.setattr("scrapers.pipelines.get_engine", lambda: engine)

    p = CinemaScraperPipeline()
    p.open_spider(MagicMock())
    return p, conn, cur


def _delete_calls(cur):
    return [c for c in cur.execute.call_args_list if "DELETE FROM showtimes" in c.args[0]]


def test_sweep_deletes_future_rows_for_written_cinemas(pipeline):
    p, conn, cur = pipeline
    p.written_cinemas = {"IFC CENTER", "METROGRAPH"}

    p.close_spider(MagicMock())

    deletes = _delete_calls(cur)
    assert len(deletes) == 2
    swept = {c.args[1][0] for c in deletes}
    assert swept == {"IFC CENTER", "METROGRAPH"}
    # Every delete is scoped to future rows untouched by this run.
    for c in deletes:
        assert "crawled_at < %s" in c.args[0]
        assert "show_time > now()" in c.args[0]
        assert c.args[1][1] == p.run_started_at
    conn.close.assert_called_once()


def test_no_sweep_for_cinema_without_successful_write(pipeline):
    p, _conn, cur = pipeline
    # A spider that never committed an item leaves written_cinemas empty.
    p.close_spider(MagicMock())
    assert _delete_calls(cur) == []


def test_sweep_error_rolls_back_and_still_closes(pipeline):
    p, conn, cur = pipeline
    p.written_cinemas = {"IFC CENTER"}
    cur.execute.side_effect = psycopg2.Error("boom")

    p.close_spider(MagicMock())  # must not raise

    conn.rollback.assert_called_once()
    cur.close.assert_called_once()
    conn.close.assert_called_once()
