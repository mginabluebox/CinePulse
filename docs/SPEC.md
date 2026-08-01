# CinePulse — Application Specification

**Status:** Descriptive spec of the system as built (branch `test`, Aug 2026).
**Scope:** Full-stack behaviour — ingestion, storage, retrieval, API, UI, deployment.

---

## 1. Product overview

CinePulse aggregates repertory and independent cinema schedules in New York City into a single
browsable calendar, and layers a natural-language recommender on top of it.

Two things the user can do:

1. **Browse** — a week-by-week showtime calendar across all tracked cinemas, with posters,
   ratings, genres, trailers, and direct ticket links.
2. **Ask** — describe a mood or taste in plain English ("something uplifting", "a mind-bender")
   and receive 5 films *that are actually playing this week*, each with a one-line reason, and
   swipe through them.

The differentiator over a cinema's own site is cross-venue coverage plus semantic search: the
user does not need to know a film's title to find it.

### Tracked cinemas

| Cinema (DB value)          | Source | Spider |
|----------------------------|--------|--------|
| `METROGRAPH`               | `metrograph.com/film/` (HTML) | `metrograph` |
| `FILM FORUM`               | `filmforum.org/now_playing` (HTML) | `film_forum` |
| `IFC CENTER`               | `ifccenter.com` (HTML) | `ifc_center` |
| `ANGELIKA NEW YORK`        | Reading Cinemas JSON API | `angelika` |
| `VILLAGE EAST BY ANGELIKA` | Reading Cinemas JSON API | `angelika` |
| `CINEMA 123 BY ANGELIKA`   | Reading Cinemas JSON API | `angelika` |

The Angelika spider fetches a bearer token from `settings/6` and then queries
`production-api.readingcinemas.com/films` per cinema ID.

---

## 2. Architecture

The system splits into two halves that **never call each other**. The offline half runs weekly
on a schedule and writes to Postgres; the online half serves requests and reads from it. The
database is the entire contract between them — there is no queue, no RPC, no shared process.

```
┌─ OFFLINE ─ weekly cron on a scheduled Fly machine ──────────────────────────┐
│                                                                             │
│   scrapers/run_spider_and_embed.py — three stages, in order                 │
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
│     OpenAI embeddings     — both search and recommend                       │
│     OpenAI | Ollama chat  — recommend only                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ▼
                 Browser — server-rendered Jinja + vanilla JS
```

### What the split buys, and what it costs

- **The two halves deploy and scale independently.** They share one Docker image but run as
  separate Fly machines with different lifecycles — the web app auto-stops to zero, the scraper
  wakes weekly. This is exactly why deploying scraper code needs the extra `fly machine update`
  step (§9): `fly deploy` only moves the web app.
- **A failed scrape degrades gracefully.** The online half keeps serving the last good snapshot;
  data goes stale rather than disappearing. The stale-showtime sweep reinforces this by never
  deleting rows for a cinema that wrote nothing this run.
- **Embeddings are precomputed, so recommendation latency is one embed + one LLM call.** The
  expensive part — embedding the whole catalogue — happens offline.
- **Freshness is bounded by the cron interval.** A film added mid-week is invisible until the
  next run, and a movie scraped but not yet embedded is invisible to *both* recommendation and
  search, since candidate selection requires a non-null `embedding`. Ordering matters: embedding
  runs before enrichment so a new film becomes searchable in the same run it is scraped.
- **Only the online half is latency-sensitive.** The offline half can retry, sleep between API
  calls, and take minutes; the online half must answer in seconds under a 60 s gunicorn timeout.

### Repository layout

| Path | Role |
|------|------|
| `src/app.py` | Flask routes, calendar assembly, caching, error → HTTP mapping |
| `src/bots/get_recommendation.py` | Two-stage recommender + semantic search |
| `src/bots/llm_selector.py` | Provider abstraction (OpenAI / Ollama), embeddings, token counting, call logging |
| `src/database/models.py` | `Movie`, `Showtime` SQLAlchemy models |
| `src/database/queries.py` | All DB reads/writes used by the web app |
| `src/database/setup_db.py` | `get_engine()` / `get_session()` — single source of DB credentials |
| `src/database/sync_embeddings.py` | Embedding generation and refresh |
| `src/database/sync_enrichment.py` | OMDb/TMDb enrichment + title backfill |
| `src/database/title_normalization.py` | Pure string logic shared by scraper and enrichment |
| `src/errors.py` | `LLMError`, `DBError`, `ParseError`, `RateLimitError` |
| `src/templates/`, `src/static/` | Jinja templates, CSS, vanilla JS |
| `scrapers/` | Scrapy project — spiders, pipelines, settings |
| `tests/` | Unit tests — flat, web app and spider parsing together |
| `scripts/` | Repeatable DB maintenance tooling (`dedup_movies.py`, `clear_enrichment.py`) - committed |
| `data/`, `notebooks/` | Scraper dumps, SQL dumps, analysis notebooks, one-off scripts - local only, not committed |

There are two import conventions in the codebase: the web app runs with `src/` on the path
(`from database.queries import …`), while scrapers and standalone scripts run from the repo
root (`from src.database.queries import …`). `title_normalization.py` is deliberately
dependency-free so it imports cleanly under both.

---

## 3. Data model

### `movies` — one row per distinct film

Identity is `(lower(trim(title)), year)`, resolved by the scraper pipeline.

| Group | Columns |
|-------|---------|
| Identity | `id`, `title`, `year`, `created_at`, `updated_at` |
| Scraped | `scraped_synopsis`, `scraped_director1`, `scraped_cinema`, `scraped_image_url`, `scraped_details_link`, `scraped_title_normalized` |
| Embedding | `embedding vector(1536)`, `embedding_model`, `embedding_source_hash`, `embedded_at` |
| External IDs | `imdb_id`, `tmdb_id` |
| OMDb ratings | `imdb_rating`, `imdb_votes`, `omdb_rt_score`, `omdb_metacritic_score` |
| TMDb metadata | `tmdb_original_title`, `tmdb_genres[]`, `tmdb_origin_countries[]`, `tmdb_original_language`, `tmdb_spoken_languages[]`, `tmdb_tagline`, `tmdb_overview`, `tmdb_runtime`, `tmdb_collection_name`, `tmdb_poster_url`, `tmdb_release_date`, `tmdb_trailer_url`, `tmdb_title_zh` |
| Bookkeeping | `enriched_at` |

`scraped_title_normalized` holds the API-lookup form of the title (see §4.2) and is what
enrichment queries OMDb/TMDb with.

### `showtimes` — one row per screening

Uniqueness constraint: **`(movie_id, show_time, cinema, format)`** — this is the `ON CONFLICT`
key for the upsert.

| Group | Columns |
|-------|---------|
| Screening | `id`, `crawled_at`, `show_time`, `show_day`, `cinema`, `ticket_link`, `details_link`, `image_url`, `special_attributes`, `trailer_url`, `format` |
| Denormalized film fields | `title`, `director1`, `director2`, `year`, `runtime`, `synopsis` |
| FK | `movie_id → movies.id` |

Film-level fields are duplicated onto showtimes so the calendar renders from a single query;
the movie row remains the canonical record for embeddings and enrichment.

`ticket_link = 'sold_out'` is a sentinel, not a URL. The recommender excludes sold-out
showtimes; the calendar renders them as a disabled chip.

### `recommendation_logs`

Every LLM call, success or failure: `queried_at`, `api_name`, `model_name`, `prompt_num_token`,
`prompt`, `response`, `error_code` (0 = success, 1 = failure), `run_id`, `session_token`.
Doubles as the rate-limiting ledger.

### `recommendation_feedback`

Swipe outcomes: `run_id`, `session_token`, `movie_id`, `liked`, `decision_ms`, `similarity`,
`title`, `year`, `created_at`.

---

## 4. Ingestion pipeline

Entry point: `python scrapers/run_spider_and_embed.py`

### 4.1 Scrape

`CrawlerProcess` runs all four spiders in one process. Each yields showtime-level items
(`scrapers/items.py`): title, show_time, show_day, ticket_link, image_url, director1/2, year,
runtime, format, synopsis.

`CinemaScraperPipeline` then, **per item**:

1. Normalizes the title (§4.2).
2. `UPDATE movies … WHERE lower(trim(title)) = lower(trim(%s)) AND year IS NOT DISTINCT FROM %s
   RETURNING id`; on no match, `INSERT … RETURNING id`.
3. Upserts the showtime row on the four-column conflict key.
4. `commit()` per item, with `rollback()` on `psycopg2.Error` — a single malformed item cannot
   poison subsequent inserts. **Replicate this pattern in any new pipeline.**
5. Records the cinema in `written_cinemas`.

**Stale sweep** (`close_spider`): for each cinema with at least one committed write this run,
delete future showtimes whose `crawled_at` predates `run_started_at`. This prunes rows orphaned
when a title, year, or format change causes the upsert to insert fresh instead of updating. Past
showtimes are retained as history. A cinema that failed to scrape entirely writes nothing and is
therefore never swept — its data survives a broken scrape.

**Dry run:** `--dry-run` swaps in `DryRunCollectorPipeline`, caps at 10 movies per cinema, writes
no DB rows, and dumps grouped JSON to `data/scraper/dry_run_<ts>.json`. It calls the same
`_prepare_item()` as the live pipeline, so title-normalization changes are exercised before any
write. All scraper crawl output belongs in `data/scraper/` (gitignored), never in `tests/`.

### 4.2 Title normalization

`src/database/title_normalization.py`, three levels:

- `_strip_display_suffix` — removes `(Open Captioning)`, `[35mm|16mm|70mm|DCP|Digital|OV]`,
  and trailing `in 35mm`; normalizes NFKC whitespace. Used for the stored `movies.title`.
- `_api_lookup_title` — the above, plus: strip `"X presents:"` prefix (all cinemas); for
  Metrograph, strip `"X selects"` prefix and `"… preceded by …"` suffix; for Film Forum, extract
  the all-caps run from director-credit titles (`"Spike Lee's CROOKLYN"` → `"CROOKLYN"`) and
  straighten curly apostrophes. Guarded by a ≥2-mixed-case-word test to avoid mangling genuinely
  all-caps titles. Stored as `scraped_title_normalized`.
- `_normalize_for_matching` — lowercased display form, for cross-cinema dedup scripts.

`script.js:normalizeTitle()` mirrors `_strip_display_suffix` so the frontend can decide whether
`tmdb_original_title` differs meaningfully from the scraped title before showing it.

### 4.3 Embedding sync

`src/database/sync_embeddings.py` — model `text-embedding-3-small`, dimension **1536**, batches
of 16 (`EMBED_BATCH_SIZE`).

Input text is deterministic: `Title: … | Year: … | Director: … | Synopsis: …`. Its SHA-256 is
stored as `embedding_source_hash`. A row is re-embedded only when the embedding is missing, the
model name changed, or the hash changed — so reruns are cheap and idempotent. `--refresh-all`
forces re-embedding; `--dry-run` reports without calling OpenAI.

Changing the embedding model requires updating the `vector(1536)` schema and the tiktoken
`o200k_base` counting in `llm_selector.py`.

### 4.4 Enrichment sync

`src/database/sync_enrichment.py` — OMDb first (for `imdb_id` and ratings), then TMDb (via
`/find` on the IMDb ID, falling back to `/search/movie`), then `/movie/{id}` with
`append_to_response=videos,translations`.

Fallback ladder for edition-suffixed titles (`"… Director's Cut"`): retry without year, then
with the suffix stripped. Trailer picks an official YouTube trailer when available; Chinese title
prefers CN > TW > HK.

Default scope: movies with a future showtime that are unenriched, have no release date, or
released within 30 days (new releases get fresh ratings). Modes: `--apply` (default is dry-run),
`--refresh-all`, `--refresh-count N` (backfill unenriched rows DB-wide), `--backfill-titles`
(recompute `scraped_title_normalized`, no API calls), `--limit`, `--sleep`.

Requires `OMDB_API_KEY` and `TMDB_API_KEY`; validated up front.

---

## 5. Retrieval and recommendation

### 5.1 Recommendation — two stages

`recommend_movies_by_embedding(preference, engine, …)`:

1. **Candidates** — `get_movies_with_future_showtimes(exclude_sold_out=True, end_date=…)`:
   movies with at least one future, non-sold-out showtime **and** a non-null embedding, grouped
   and ordered by earliest upcoming showtime.
2. **Embed** the user's preference once (`generate_embedding`).
3. **Score** every candidate by cosine similarity in Python (`_score_candidates_by_similarity`),
   keep the top **30**.
4. **Re-rank** — one LLM call (`max_tokens=512`, `temperature=0`) asking for exactly 5 picks as
   `{"movie_id": "reason", …}`.
5. **Parse** — `_parse_movie_reason_map()` strictly validates the JSON, coercing keys to int and
   raising `ParseError` if nothing numeric survives. LLM ordering is preserved; capped at 5.
6. **Hydrate** — fetch up to 5 upcoming non-sold-out showtimes per selected movie, group by
   cinema, resolve poster (`scraped_image_url` → showtime `image_url` → `tmdb_poster_url`).
   A selection with no remaining future showtime is dropped with a warning.

**Timezone note:** step 1 deliberately passes `start_date=None` so the cutoff is Postgres
`func.now()`. Passing the app's ET-formatted string would be read as UTC, a 4-hour offset that
lets already-started screenings through as candidates. The showtime hydration in step 6 uses the
same `func.now()` cutoff, so the two stages agree.

Prompt structure and `_parse_movie_reason_map()` are coupled — changing one requires updating
the other and `tests/test_recommendation_units.py`.

### 5.2 Semantic search — retrieval only

`search_showtimes_by_embedding(query, engine)` skips the LLM entirely. It embeds the query,
scores *all* movies with future showtimes, then walks the ranked list applying a **per-cinema
quota of 30**: a movie qualifies if any of its cinemas still has quota left. This guarantees
every venue contributes results rather than one cinema's catalogue dominating the global ranking.
Up to 20 showtimes per movie are returned.

### 5.3 LLM provider abstraction

`LLM_PROVIDER` selects `openai` (default model `gpt-4o-mini`) or `ollama` (default
`llama3.1:8b`, 120 s timeout). Any other value raises at import.

Embeddings **always** go through OpenAI regardless of chat provider — `OPENAI_API_KEY` is
required even when running Ollama for chat.

`call_llm()` writes a `recommendation_logs` row on both success (`error_code=0`) and failure
(`error_code=1`), with prompt token count from tiktoken `o200k_base`. Logging failures are
swallowed so they never break the request. Any provider exception is wrapped as `LLMError`.

---

## 6. HTTP API

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Landing page — 7-day calendar from *now*, cached 300 s |
| GET | `/app` | Recommendation page (swipe UI) |
| GET | `/api/calendar_week/<int:week_num>` | Weeks 2+ as rendered HTML fragments, cached 300 s |
| POST | `/api/recommend_movies` | Two-stage recommendation |
| POST | `/api/search_showtimes` | Semantic showtime search |
| POST | `/api/feedback` | Record a swipe |

### `POST /api/recommend_movies`

```jsonc
// request
{ "preference": "something uplifting", "session_token": "<uuid>" }

// 200
{ "run_id": "<uuid>", "results": [ {
    "movie_id": 123, "id": 123, "title": "...", "year": 1994,
    "director": "...", "synopsis": "...", "similarity": 0.42,
    "reason": "Why you might like it…",
    "showtimes": [ … ],
    "cinemas": [ { "cinema": "METROGRAPH", "showtimes": [ … ] } ],
    "scraped_image_url": "...", "imdb_rating": 8.1, "omdb_rt_score": 92,
    "omdb_metacritic_score": 78, "tmdb_genres": ["Drama"],
    "tmdb_original_title": "...", "scraped_title_normalized": "...",
    "tmdb_trailer_url": "..."
} ] }
```

- **429** `{ "error": "<message>", "rate_limited": true }` when a limit is hit.
- **502** for `LLMError` / `DBError` / `ParseError`.
- **500** for anything else.

`run_id` is a fresh UUID per request and ties the LLM log to subsequent feedback rows.

### `POST /api/search_showtimes`

Request `{ "query": "..." }`. Returns a bare JSON array of movie objects (same shape minus
`reason`/`cinemas`, plus `runtime` and `image_url`). Empty query → `[]`. Same 502/500 mapping.

### `POST /api/feedback`

Request requires `movie_id` and `liked`; optional `run_id`, `session_token`, `decision_ms`,
`similarity`, `title`, `year`. Missing required fields → **400**. Success → `{"status":"ok"}`.

### Error contract

`LLMError`, `DBError`, `ParseError` → **502**. Any new error type crossing an API boundary must
be wrapped into one of these to preserve the contract.

### Rate limiting

Applied **only** when `LLM_PROVIDER == 'openai'`, counting successful calls (`error_code = 0`)
since `date_trunc('day', now())`:

- `DAILY_GLOBAL_LIMIT = 35` — all users combined.
- `SESSION_LIMIT = 5` — per `session_token`.

The session token is a `crypto.randomUUID()` persisted in `localStorage` under
`cinepulse_session_token`. It identifies a browser, not a person, and is trivially resettable —
it is a cost guardrail, not a security control.

---

## 7. Frontend

Server-rendered Jinja + vanilla JS. No build step, no framework.

### Landing page (`/`)

- 7-day calendar, day tabs + panels. Weeks 2+ load on demand via `/api/calendar_week/<n>`,
  which returns pre-rendered `tabs` and `panels` HTML — the same macros the server used for
  week 1, so markup stays identical across weeks.
- `total_weeks` is derived from the furthest `show_time` in the DB, so navigation never offers
  an empty week.
- Cinema filter pills; inline semantic search that swaps the calendar view for a paginated
  results view (10 per page) with a Back control.
- `build_calendar()` groups by `(movie_id, cinema)` per date, backfills missing
  poster/synopsis/details from any showtime in the group, and sorts films by earliest screening.
  Showtimes are bucketed into morning (< 12:00), afternoon (< 17:00), evening.

### Recommendation page (`/app`)

- Free-text preference → 5 stacked swipe cards (pointer events, 120 px threshold, rotation
  proportional to drag).
- Each swipe POSTs to `/api/feedback` with `decision_ms` measured from pointerdown; failures are
  swallowed so the interaction never blocks.
- When the deck empties, a summary renders — liked first, then by similarity, then by earliest
  showtime — using the same film-banner component as search results.

### Shared rendering

`renderFilmBanner()` in `script.js` mirrors the `render_film_banner` Jinja macro in
`_week_panels.html`. Rating chips are colour-coded (IMDb ≥ 7 good / ≥ 4 meh; RT ≥ 60 fresh;
Metacritic ≥ 61 good / ≥ 40 meh) with brand icons from Wikimedia. `tmdb_original_title` renders
only when it differs from the normalized scraped title. All interpolated values pass through
`esc()` / `escAttr()`.

### Design system

Editorial, indie-cinema aesthetic — warm, typographically controlled, understated.

- **Palette:** only the `:root` CSS variables — `--cp-bg`, `--cp-surface`, `--cp-border`,
  `--cp-text`, `--cp-text-muted`, `--cp-accent`, `--cp-navy`. No new colours.
- **Type:** Space Grotesk for headings/labels/nav; system UI stack for body. Uppercase +
  letter-spacing for labels and section titles.
- **Hierarchy:** section titles in `--cp-text` with a border-bottom (editorial divider);
  sub-labels such as cinema names in `--cp-text-muted`, lighter and smaller.
- **Accent red** is reserved for primary actions, hover, and active indicators — never
  decoration.
- **New components** follow existing patterns: pill buttons match `.cp-cinema-filter-btn`, text
  toggles match `.cp-show-more-btn`, inline links match `.cp-details-arrow`.

---

## 8. Configuration

```
DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME

LLM_PROVIDER            # "openai" | "ollama"   (default: ollama)
OPENAI_API_KEY          # required for embeddings in all modes
OPENAI_MODEL            # default gpt-4o-mini
OPENAI_EMBED_MODEL      # default text-embedding-3-small
OLLAMA_BASE             # default http://localhost:11434/api
OLLAMA_MODEL            # default llama3.1:8b

OMDB_API_KEY            # enrichment only
TMDB_API_KEY            # enrichment only
EMBED_BATCH_SIZE        # default 16
```

Loaded from `.env` via `python-dotenv`. All DB access goes through
`src/database/setup_db.get_engine()` so credentials are resolved in exactly one place.

---

## 9. Deployment

Fly.io app `cinepulse`, region `sjc`. Two independent processes:

| Process | Managed by | Update path |
|---------|-----------|-------------|
| Web app | `fly.toml` — 512 MB, shared CPU, auto-start/stop, `min_machines_running = 0` | `fly deploy` |
| Scraper | Standalone machine, `--schedule weekly`, 256 MB | `fly deploy` **+** `fly machine update` |

The Dockerfile is `python:3.12-slim`, swaps `psycopg2` for `psycopg2-binary`, and serves via
`gunicorn app:app --bind 0.0.0.0:8080 --workers 1 --timeout 60` with WORKDIR `/app/src`.

App-only changes: `fly deploy --depot=false`. The scheduled scraper machine is pinned to the
image digest it was created with and is unaffected.

Scraper code changes need the extra step — after `fly deploy`, re-point the machine:

```bash
fly machines list --app cinepulse
fly machine update <machine-id> --image registry.fly.io/cinepulse:latest --app cinepulse
```

Smoke-test a new image as a one-off machine (no `--schedule`) before scheduling it.

Caching is in-process `SimpleCache` (300 s) — with `workers = 1` and auto-stop machines it is
per-machine and cold on wake. Fine for the current traffic profile; a shared cache would be
needed before scaling out.

---

## 10. Testing

`source venv-test/bin/activate && pytest tests/`

| File | Covers |
|------|--------|
| `test_recommendation_units.py` | Prompt building, `_parse_movie_reason_map`, cosine similarity |
| `test_recommendation_helpers.py` | Candidate scoring, showtime grouping |
| `test_api_behavior.py` | Route behaviour with mocked recommender |
| `test_api_error_mapping.py` | Error type → HTTP status contract |
| `test_pipeline_sweep.py` | Stale-showtime sweep semantics |
| `test_openai.py` | Provider call shape — `@pytest.mark.integration`, billed, deselected by default |
| `test_film_forum_spider.py` | Film Forum parsing (31 cases) |

Parsing edge cases and the regression URLs behind them are documented in
**AGENTS.md § Scraper edge cases**.

`pytest tests/` runs the mocked suite only. Integration tests that hit live APIs are marked
`integration` and excluded by the `addopts` in `pytest.ini`; run them with `pytest -m integration`.

New DB-facing code should get lightweight unit tests that mock engines and cursors rather than
requiring a live Postgres.

---

## 11. Known constraints

- **Similarity is computed in Python, not pgvector.** Every recommendation loads all candidate
  embeddings (1536 floats each) into the app and scores them in a loop. Correct, and fine at
  current catalogue size, but it does not use the pgvector index and grows linearly with the
  catalogue. Moving to a `<=>` ORDER BY in SQL is the obvious scaling step.
- **`uq_movie_title_year` is commented out** in `models.py`. Movie identity is enforced only by
  the pipeline's UPDATE-then-INSERT logic, so concurrent scrapes could duplicate a film.
  `scripts/dedup_movies.py` exists to clean up after this.
- **Film-level fields are duplicated** across `movies` and `showtimes` and can drift; the
  calendar reads the showtime copy, the recommender reads the movie copy.
- **Rate limits are per-browser**, resettable by clearing `localStorage`.
- **Film Forum synopses intentionally include the metadata block** — that is source formatting,
  not a parsing bug.
- **Ollama mode still requires an OpenAI key** for embeddings.

---

## 12. Roadmap

- pgvector-native similarity search (`<=>`) instead of in-process scoring.
- Restore the movie uniqueness constraint after a dedup pass.
- RAG — quote synopsis content directly in the recommendation reason.
- Cache recommendations per time window for stable results.
- Expand cinema coverage.
- Use accumulated `recommendation_feedback` to evaluate and tune ranking.
