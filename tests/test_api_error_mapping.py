import pytest
import app as app_module
from errors import LLMError, DBError, ParseError


@pytest.mark.parametrize("exc", [LLMError("x"), ParseError("x"), DBError("x")])
def test_recommend_movies_returns_502_on_known_errors(monkeypatch, client, exc):
    monkeypatch.setattr(app_module, "recommend_movies_by_embedding",
                        lambda *a, **k: (_ for _ in ()).throw(exc))
    res = client.post("/api/recommend_movies", json={"preference": "action"})
    assert res.status_code == 502
    assert "error" in res.get_json()
