from unittest.mock import MagicMock
import app as app_module


def test_recommend_movies_happy_path(monkeypatch, client):
    monkeypatch.setattr(app_module, "recommend_movies_by_embedding",
                        lambda *a, **k: [{"movie_id": 1, "title": "Test"}])
    res = client.post("/api/recommend_movies", json={"preference": "action"})
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data.get("run_id"), str)
    assert isinstance(data.get("results"), list)


def test_feedback_missing_movie_id(client):
    res = client.post("/api/feedback", json={"liked": True})
    assert res.status_code == 400


def test_feedback_missing_liked(client):
    res = client.post("/api/feedback", json={"movie_id": 1})
    assert res.status_code == 400


def test_feedback_valid(monkeypatch, client):
    mock_feedback = MagicMock()
    monkeypatch.setattr(app_module, "insert_recommendation_feedback", mock_feedback)
    res = client.post("/api/feedback", json={"movie_id": 99999, "liked": True})
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}
    mock_feedback.assert_called_once()


def test_search_showtimes_happy_path(monkeypatch, client):
    monkeypatch.setattr(app_module, "search_showtimes_by_embedding",
                        lambda *a, **k: [{"movie_id": 2, "title": "Film"}])
    res = client.post("/api/search_showtimes", json={"query": "comedy"})
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)
