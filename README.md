# CinePulse

Curates local cinema schedule and uses an LLM to recommend what to watch.

**Live demo:** https://cinepulse-ct8r.onrender.com/  
<p align="center">
  <img src="assets/CinePulse_Demo_20260301.gif" width="500" />
</p>

## Stack
- Flask UI/API: [src/app.py](src/app.py)
- LLM selector (ollama or OpenAI) and recommendation: [src/bots/llm_selector.py](src/bots/llm_selector.py), [src/bots/get_recommendation.py](src/bots/get_recommendation.py)
- Postgres (+ pgvector) + SQLAlchemy database: [src/database/models.py](src/database/models.py), [src/database/queries.py](src/database/queries.py)
- Scrapy ETL: [scrapers/spiders/metrograph_spider.py](scrapers/spiders/metrograph_spider.py), [scrapers/pipelines.py](scrapers/pipelines.py)

## Data flow
1) Scrapy spider harvests showtimes → writes to Postgres.  
2) Two-stage recommendation pipeline: user preferences are embedded and compared to film embeddings via cosine similarity to retrieve top-K candidate movies, then an LLM re-ranks and outputs the top 5 recommendations in structured JSON.
4) UI renders recommendations with reasons + upcoming showtimes.

## Quickstart
Requirements: Python 3.10+, Postgres with pgvector, optional OpenAI key.

1) Install: `pip install -r requirements.txt`
2) Env: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `OPENAI_API_KEY` (if using OpenAI), `LLM_PROVIDER` (`openai` or `ollama`).
3) Run: `export FLASK_APP=src/app.py && flask run` (optional: `python scrapers/run_spider.py` to update showtimes; `python src/database/sync_embeddings.py` to embed film metadata).

## Next
- Augment film metadata (genre etc.) from TMDB. Add filtering for showtimes table.
- Add RAG to directly quote synopsis content in reason.
- Add caching for stable recommendations per time window.
- Expand to more cinemas.
- UI polish: richer cards and mobile-first layout.
