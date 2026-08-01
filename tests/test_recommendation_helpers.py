from bots.get_recommendation import recommend_movies_by_embedding, _score_candidates_by_similarity


def test_embedding_recommender_ranks_and_groups(monkeypatch):
    candidates = [
        {"movie_id": 1, "title": "A", "embedding": [1, 0], "synopsis": "A", "director": "D"},
        {"movie_id": 2, "title": "B", "embedding": [0, 1], "synopsis": "B", "director": "E"},
    ]

    monkeypatch.setattr('bots.get_recommendation.get_movies_with_future_showtimes',
                        lambda engine=None, exclude_sold_out=False, end_date=None: candidates)
    monkeypatch.setattr('bots.get_recommendation.generate_embedding', lambda mood: [1, 0])
    monkeypatch.setattr('bots.get_recommendation.call_llm', lambda *a, **k: '{"1": "pick A", "2": "pick B"}')
    monkeypatch.setattr('bots.get_recommendation.get_future_showtimes_for_movie_ids', lambda movie_ids, limit_per_movie, engine=None, exclude_sold_out=False: {
        1: [{"cinema": "C1", "showdate": "2025-01-01", "showtime": "08:00", "ticket_link": "t1"}],
        2: [{"cinema": "C2", "showdate": "2025-01-02", "showtime": "09:00", "ticket_link": "t2"}],
    })

    recs = recommend_movies_by_embedding("mood", db_engine=None, top_k=2, showtimes_per_movie=5)
    assert len(recs) == 2
    assert recs[0]['movie_id'] == 1
    assert recs[0]['reason'] == 'pick A'
    assert any(c['cinema'] == 'C1' for c in recs[0]['cinemas'])


def test_score_candidates_by_similarity_orders_top():
    scored = _score_candidates_by_similarity([1, 0], [
        {"movie_id": 1, "embedding": [0, 1]},
        {"movie_id": 2, "embedding": [1, 0]},
    ], top_n=1)
    assert len(scored) == 1
    assert scored[0]['movie_id'] == 2
