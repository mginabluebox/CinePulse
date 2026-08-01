# Architecture

The system splits into two halves that **never call each other**. The offline half runs weekly on
a schedule and writes to Postgres; the online half serves requests and reads from it. 

```
┌─ OFFLINE ─ weekly cron on a scheduled Fly machine ──────────────────────────┐
│                                                                             │
│   scrapers/run_spider_and_embed.py - three stages, in order                 │
│                                                                             │
│   cinema sites ────► ① Scrapy spiders ──► CinemaScraperPipeline             │
│   + JSON APIs           metrograph · film_forum    per-item commit,         │
│                         ifc_center · angelika      rollback on error,       │
│                                                    stale-showtime sweep     │
│                                                                             │
│   OpenAI embed ────► ② sync_embeddings.py                                   │
│   API                   source-hash gated · batches of 16                   │
│                         → movies.embedding vector(1536)                     │
│                                                                             │
│   OMDb + TMDb ─────► ③ sync_enrichment.py                                   │
│   APIs                  ratings · genres · posters · trailers               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │ writes
                                       ▼
             ╔══════════════════════════════════════════════════╗
             ║  PostgreSQL + pgvector                           ║
             ║                                                  ║
             ║  movies · showtimes                              ║
             ║  recommendation_logs · recommendation_feedback   ║
             ╚══════════════════════════════════════════════════╝
                   ▲ reads                 │ writes
                   │                       ▼ logs · feedback
┌─ ONLINE ─ per request, Flask on gunicorn (1 worker, auto-stop) ─────────────┐
│                                                                             │
│   GET  /                       get_showtimes → build_calendar               │
│                                → Jinja                 ⟨cache 300s⟩         │
│   GET  /api/calendar_week/<n>  same, as HTML fragments ⟨cache 300s⟩         │
│                                                                             │
│   POST /api/search_showtimes   embed query → cosine rank                    │
│                                → per-cinema quota of 30                     │
│   POST /api/recommend_movies   embed → top 30 by cosine → LLM               │
│                                re-rank to 5 → hydrate showtimes             │
│   POST /api/feedback           insert swipe row                             │
│                                                                             │
│   request-time external calls:                                              │
│     OpenAI embeddings     - both search and recommend                       │
│     OpenAI | Ollama chat  - recommend only                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ▼
                 Browser - server-rendered Jinja + vanilla JS
```

Concretely, that means: the offline half can retry, sleep between API calls, and take minutes; the
online half must answer within the 60 s gunicorn timeout. A movie is visible to search and
recommendation only once it has an embedding, so the two stages run in the order shown.

Why the system is split this way, and what the split costs, is in
[decisions.md](decisions.md#1-the-database-is-the-only-contract-between-ingestion-and-serving).

## Repository layout

| Path | Role |
|------|------|
| `src/app.py` | Flask routes, calendar assembly, caching, error → HTTP mapping |
| `src/bots/get_recommendation.py` | Two-stage recommender + semantic search |
| `src/bots/llm_selector.py` | Provider abstraction (OpenAI / Ollama), embeddings, token counting, call logging |
| `src/database/models.py` | `Movie`, `Showtime` SQLAlchemy models |
| `src/database/queries.py` | All DB reads/writes used by the web app |
| `src/database/setup_db.py` | `get_engine()` / `get_session()` - single source of DB credentials |
| `src/database/sync_embeddings.py` | Embedding generation and refresh |
| `src/database/sync_enrichment.py` | OMDb/TMDb enrichment + title backfill |
| `src/database/title_normalization.py` | Pure string logic shared by scraper and enrichment |
| `src/errors.py` | `LLMError`, `DBError`, `ParseError`, `RateLimitError` |
| `src/templates/`, `src/static/` | Jinja templates, CSS, vanilla JS |
| `scrapers/` | Scrapy project - spiders, pipelines, settings |
| `tests/` | Unit tests - flat, web app and spider parsing together |
| `scripts/` | Repeatable DB maintenance tooling (`dedup_movies.py`, `clear_enrichment.py`), committed |
| `data/`, `notebooks/` | Scraper dumps, SQL dumps, analysis notebooks, one-off scripts - local only, not committed |
| `docs/` | This documentation |
| `AGENTS.md` | Working instructions for agents and maintainers (`CLAUDE.md` is a symlink to it) |

There are two import conventions in the codebase: the web app runs with `src/` on the path
(`from database.queries import …`), while scrapers and standalone scripts run from the repo root
(`from src.database.queries import …`). `title_normalization.py` is deliberately dependency-free
so it imports cleanly under both.

## LLM provider abstraction

`src/bots/llm_selector.py` reads `LLM_PROVIDER` and selects `openai` (default model `gpt-4o-mini`)
or `ollama` (default `llama3.1:8b`, 120 s timeout). Any other value raises at import.

- `generate_embedding()` **always** calls OpenAI, whichever chat provider is configured.
- `call_llm()` writes a `recommendation_logs` row on both success (`error_code=0`) and failure
  (`error_code=1`), with prompt token count from tiktoken `o200k_base`. Logging failures are
  swallowed so they never break the request.
- Any provider exception is wrapped as `LLMError`.

## Error contract

`LLMError`, `DBError`, `ParseError` map to **502**. `RateLimitError` is caught in
`/api/recommend_movies` and turned into a **429**. Anything else is **500**.

Any new error type that can cross an API boundary must be wrapped into one of these so the
contract holds. `tests/test_api_error_mapping.py` pins this.

## Caching

In-process `SimpleCache` with a 300 s timeout, applied to `/` and `/api/calendar_week/<n>`. With
`workers = 1` and auto-stopping machines the cache is per-machine and cold on every wake. Its limits
are covered in [decisions.md](decisions.md#11-caching-is-in-process-and-per-machine).

## Deployment topology

Fly.io app `cinepulse`, region `sjc`. Two independent processes from one image:

| Process | Managed by | Lifecycle |
|---------|-----------|-----------|
| Web app | `fly.toml` - 512 MB, shared CPU, auto-start/stop, `min_machines_running = 0` | Scales to zero between requests, wakes on traffic |
| Scraper | Standalone machine, `--schedule weekly`, 256 MB | Wakes weekly, runs the pipeline, exits |

The Dockerfile is `python:3.12-slim`, swaps `psycopg2` for `psycopg2-binary`, and serves via
`gunicorn app:app --bind 0.0.0.0:8080 --workers 1 --timeout 60` with WORKDIR `/app/src`.

**`fly deploy` moves only the web app.** The scheduled scraper machine is pinned to the image digest
it was created with, so scraper code changes need a second step to re-point it.

The deploy and smoke-test commands are a runbook, not architecture: see
[AGENTS.md](../AGENTS.md#deployment-runbook).

### Continuous deployment

`.github/workflows/fly-deploy.yml` runs `flyctl deploy --remote-only` on **every push to `main`**.

Two things follow that are easy to get wrong:

- **Merging to `main` ships to production immediately.** There is no staging environment and no
  manual gate.
- **No tests run in CI.** The workflow checks out, installs flyctl, and deploys. `pytest` is never
  invoked, so a green pipeline means "the image built", not "the code works". Test discipline is
  entirely local.

The scheduled scraper machine is unaffected by this workflow, for the same digest-pinning reason as
a manual deploy.

## Failure modes

What actually happens when each dependency fails, and what the user sees.

| Failure | Behaviour | User impact |
|---------|-----------|-------------|
| A spider is blocked or errors | It commits nothing, so `written_cinemas` excludes it and the stale sweep never touches its rows | That cinema's schedule stays at last week's data. Silent - no alert exists |
| The whole scrape fails | Nothing is written or deleted | Data goes stale, nothing disappears |
| OpenAI embeddings down (offline) | `sync_embeddings` raises and rolls back the current batch; earlier batches are already committed | New films stay unembedded, so they are invisible to *both* search and recommendation until the next run |
| OMDb/TMDb down | Enrichment logs and continues to the next movie | Films render without ratings, genres, or posters |
| OpenAI embeddings down (request time) | `LLMError` → 502 | Both search and recommendation fail |
| Chat LLM down or slow | `LLMError` → 502, or the 60 s gunicorn timeout | Recommendation fails; search and calendar are unaffected |
| Postgres unreachable | `DBError` → 502 on every route | Total outage |
| Rate limit hit | 429 with `rate_limited: true` | Recommendation only; browsing and search still work |

The offline half fails toward staleness; the online half fails toward 502.

## Observability

There is no metrics stack, no error tracker, and no alerting. What exists:

- **`recommendation_logs`** is the real debugging surface. Every LLM call is stored verbatim with
  its prompt, response, token count, `error_code`, `run_id`, and `session_token`. To investigate a
  bad recommendation, find the row by `run_id` and read the prompt that produced it: the candidate
  list is right there, so you can tell retrieval failures (the right film was never a candidate)
  from re-ranking failures (it was a candidate and the model passed it over).
- **`recommendation_feedback`** joins to those rows on `run_id`, so likes and dislikes can be
  attributed back to a specific prompt and similarity score.
- **`showtimes.crawled_at`** is the freshness signal. `get_last_scraped_at()` surfaces the max as a
  stamp on the landing page.
- **Application logs** go to stdout and are visible with `fly logs`. Every route logs exceptions via
  `app.logger.exception`; the scraper pipeline logs DB errors and sweep counts per cinema.

## Testing

The test suite, what it covers, and how it is structured. The rules about which tests to run and
which cost money are in [AGENTS.md](../AGENTS.md#before-you-merge).

| File | Covers |
|------|--------|
| `test_recommendation_units.py` | Prompt building, `_parse_movie_reason_map`, cosine similarity |
| `test_recommendation_helpers.py` | Candidate scoring, showtime grouping |
| `test_api_behavior.py` | Route behaviour with mocked recommender |
| `test_api_error_mapping.py` | Error type → HTTP status contract |
| `test_pipeline_sweep.py` | Stale-showtime sweep semantics |
| `test_dry_run_collector.py` | Per-cinema quota and spider-close behaviour of `DryRunCollectorPipeline` |
| `test_film_forum_spider.py` | Film Forum parsing, pinned HTML fixtures |
| `test_openai.py` | Provider call shape. Marked `integration`: hits a live billed API, deselected by default |

Everything except `test_openai.py` runs fully mocked - no database, no network. `pytest.ini` sets
`addopts = -m "not integration"` so the billed tests are excluded unless asked for explicitly.

`tests/conftest.py` puts both `src/` and the repo root on `sys.path`, which is what lets one flat
test directory import code written under either of the two import conventions. It also loads the
real `.env`, and carries an autouse fixture that stubs out `insert_recommendation_feedback` as a
safety net against tests writing to the production database.

Parsing edge cases and the regression URLs behind them live in [AGENTS.md](../AGENTS.md) under
"Scraper edge cases".

## Known constraints and roadmap

Both live in [decisions.md](decisions.md), where each limitation is stated as the cost of the
decision that produced it: [what we would change next](decisions.md#what-we-would-change-next).
