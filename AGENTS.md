# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Always activate the virtual environment first:
```bash
source venv/bin/activate
```

**Run the app:**
```bash
export FLASK_APP=src/app.py && flask run
# or
python src/app.py
```

**Run all tests:**
```bash
source venv-test/bin/activate
pytest tests/
```

**Run a single test file:**
```bash
pytest tests/test_recommendation_helpers.py
```

**Sync movie embeddings (preview / write):**
```bash
python src/database/sync_embeddings.py --dry-run
python src/database/sync_embeddings.py
python src/database/sync_embeddings.py --refresh-all  # re-embed all rows
```

**Run the scraper:**
```bash
python scrapers/run_spider_and_embed.py
```

## Architecture

CinePulse scrapes cinema schedules, stores them in PostgreSQL with pgvector embeddings, and serves LLM-driven movie recommendations via a Flask API.

### Data flow
1. **Scrapy ETL** (`scrapers/`) → harvests Metrograph showtimes into `movies` and `showtimes` tables via `scrapers/pipelines.py`
2. **Embedding sync** (`src/database/sync_embeddings.py`) → calls OpenAI `text-embedding-3-small`, stores 1536-dim vectors in `movies.embedding`; skips rows unless content hash or model changes
3. **Recommendation API** (`POST /api/recommend_movies`) → two-stage pipeline:
   - Stage 1: cosine similarity search (pgvector) against all movies with future showtimes → top 30 candidates
   - Stage 2: LLM re-ranks to 5, returns `{movie_id: reason}` JSON
4. **Frontend** (`src/static/script.js`) → renders movie cards with swipe-based feedback; posts likes/dislikes to `/api/feedback`

### Key files
- `src/app.py` — Flask routes, caching, error mapping
- `src/bots/get_recommendation.py` — `recommend_movies_by_embedding()`, similarity scoring (`_score_candidates_by_similarity`), prompt building (`build_movie_prompt`), response parsing (`_parse_movie_reason_map`)
- `src/bots/llm_selector.py` — provider abstraction (`LLM_PROVIDER=openai|ollama`), `call_llm()`, `generate_embedding()`, token counting via tiktoken `o200k_base`
- `src/database/models.py` — `Movie` and `Showtime` SQLAlchemy models
- `src/database/queries.py` — all DB reads/writes; `get_movies_with_future_showtimes()` is the retrieval entry point
- `src/database/setup_db.py` — `get_engine()` / `get_session()`; all code must go through this for consistent credentials

### Environment variables (`.env`)
```
DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
LLM_PROVIDER          # "openai" or "ollama"
OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EMBED_MODEL
OLLAMA_BASE, OLLAMA_MODEL
```

## Scraper edge cases

Every rule below traces to a real bug. They look like over-complication; do not simplify them
away. The Film Forum cases are pinned as HTML fixtures in `tests/test_film_forum_spider.py`.
The IFC ones have no test coverage yet, so verify those by hand against the URLs at the end
of this section.

### All spiders

- **`_clean()` every string field at yield time.** Each spider defines its own `_clean()` that
  strips `\xa0` and trims. Wrap any new string field you add to a yield dict. Title whitespace
  additionally goes through `_normalize_whitespace()` in `pipelines._prepare_item`, but synopsis,
  director, and format rely solely on the spider's `_clean()`.
- **Why it matters:** movies are matched on `lower(trim(title))` + `year IS NOT DISTINCT FROM`.
  Postgres `trim()` does not strip `\xa0`, so one non-breaking space - or a `NULL` year - silently
  creates a duplicate movie row. Both have happened (Film Forum REUNION, DAYS AND NIGHTS IN THE
  FOREST); `scripts/dedup_movies.py` exists to clean up after it.
- **The stale-showtime sweep is scoped to `written_cinemas`.** `close_spider` only deletes future
  showtimes for cinemas that committed at least one item this run, so a spider that fails or gets
  blocked cannot wipe that cinema's schedule. Preserve this when touching `pipelines.py`.
- **Every spider must declare `cinemas = [...]`**, listing each cinema name it emits. `--dry-run`
  caps collection per cinema and stops a spider by closing its engine, which cancels in-flight
  requests. One spider can serve several venues (Angelika fans out to one request per venue), so
  `DryRunCollectorPipeline` waits until *all* of a spider's declared cinemas hit the quota before
  closing. A spider that omits the attribute still works but stops conservatively late.

### IFC Center

- Detail pages come in two shapes: **with** and **without** `<ul class="schedule-list">`. Both need
  handling - before the fallback XPath existed, the no-schedule-list variant yielded `synopsis = None`.
- Anchor to `schedule-list[last()]`. The first one is often a "Special Events" Q&A block rather than
  the ticket block.
- `<ul class="schedule-list">` is ticket-buying UI and **never** belongs in the synopsis. But `<p>`
  event/Q&A paragraphs in the synopsis zone ("Thursday, April 9 at 6:30: Q&A with...") **do** belong.
  A weekday-prefix filter was deliberately removed - do not reintroduce it.
- The `Director` metadata field is one comma-separated string; split it into `director1` / `director2`.

### Film Forum

- Extract synopsis text from the **full subtree** (`::text` / `_text_with_br`), never `./text()`.
  Opening sentences routinely sit inside `<em>` / `<strong>` / `<a>` children, so direct-text-only
  extraction starts the synopsis mid-sentence.
- Walk `div.copy`'s direct children and **break at the first `<h3>`**. `css('div.copy p')` grabs every
  `<p>` in document order, dragging in review pull-quotes that follow `<h3>Reviews</h3>`.
- **Pattern B pages put the metadata `<strong>` block and the prose in the same `<p>`**, split by
  `<br><br>`. Never skip a whole paragraph just because it matches "Directed by" - that drops the
  synopsis entirely.
- The metadata block (year / director / runtime) **intentionally remains** in the stored synopsis.
  That is source formatting, not a parsing bug - do not "fix" it.
- Year extraction must be an unanchored `re.search(r'\b((?:19|20)\d{2})\b', line)`. The metadata line
  reads `India, 1970` - country first, year second - so an anchored `^(\d{4})` never matches.
- Showtimes carry no AM/PM. Heuristic in `_parse_film_forum_time`: hours 1-9 are PM, 10 and 11 are AM,
  12 stays noon.

### Regression URLs

Re-check these pages after any spider or pipeline change; each one broke the parser at least once.

```
IFC   no schedule-list             https://www.ifccenter.com/films/miroirs-no-3/
IFC   event/Q&A paras in synopsis  https://www.ifccenter.com/films/steal-this-story-please/
IFC   two schedule-lists           https://www.ifccenter.com/films/the-christophers/
FF    prose inside <em>            https://filmforum.org/film/reunion
FF    reviews after <h3>           https://filmforum.org/film/living-the-land
FF    Pattern B shared <p>         https://filmforum.org/film/days-and-nights-in-the-forest
FF    Pattern B shared <p>         https://filmforum.org/film/monte-carlo-the-lubitsch-touch
```

Dry-run the whole set without touching the DB:
```bash
python scrapers/run_spider_and_embed.py --dry-run   # writes data/scraper/dry_run_<ts>.json
```

## Infrastructure & deployment

### Two separate processes on Fly.io

| Process | Managed by | How to update |
|---------|-----------|---------------|
| Web app | `fly.toml` (auto-scaling) | `fly deploy` |
| Scraper (weekly cron) | Standalone Fly machine (`--schedule weekly`) | `fly deploy` + `fly machine update` (see below) |

### Deploying app-only changes
```bash
fly deploy --depot=false
```
The scheduled scraper machine is pinned to the image digest it was created with — it is unaffected.

### Deploying scraper code changes
After `fly deploy`, the scheduled machine still points to the old image digest. Re-point it:
```bash
# 1. Find the scraper machine ID
fly machines list --app cinepulse

# 2. Update it to the new latest image
fly machine update <machine-id> --image registry.fly.io/cinepulse:latest --app cinepulse
```

### First-time setup (create the scheduled machine)
If the scraper machine is ever deleted, recreate it with:
```bash
fly machine run registry.fly.io/cinepulse:latest \
  --app cinepulse \
  --schedule weekly \
  --command "python /app/scrapers/run_spider_and_embed.py" \
  --region sjc \
  --vm-memory 256
```

### Smoke-testing a new image before scheduling
Run the scraper as a one-off machine (no `--schedule`) to verify DB connectivity and clean exit:
```bash
fly machine run registry.fly.io/cinepulse:latest \
  --app cinepulse \
  --command "python /app/scrapers/run_spider_and_embed.py" \
  --region sjc --vm-memory 256

# Tail logs (replace <machine-id> from output above)
fly logs --app cinepulse --machine <machine-id>
```

## Design principles

CinePulse has an editorial, indie-cinema aesthetic — warm, typographically controlled, and intentionally understated. All UI work must stay consistent with this vibe.

- **Palette**: use the CSS variables defined in `:root` (`--cp-bg`, `--cp-surface`, `--cp-border`, `--cp-text`, `--cp-text-muted`, `--cp-accent`, `--cp-navy`). Do not introduce new colours.
- **Typography**: Space Grotesk (via Google Fonts) for all headings, labels, and navigation. System UI stack for body/meta text. Uppercase + letter-spacing for labels and section titles.
- **Visual hierarchy**: section titles use `var(--cp-text)` (dark) and a border-bottom to feel like editorial dividers; sub-labels (e.g. cinema names within a period) use `var(--cp-text-muted)`, lighter weight, and smaller size to clearly read as secondary.
- **Interactive elements**: accent red (`var(--cp-accent)`) for primary actions, hover states, and active indicators only — not decoration.
- **Spacing**: prefer generous whitespace between sections; keep component interiors tight and scannable.
- **New UI components**: follow existing patterns — pill buttons match `.cp-cinema-filter-btn`, text toggles match `.cp-show-more-btn`, inline links match `.cp-details-arrow`. Don't invent new visual languages.

## Important conventions

- **Error types**: `LLMError`, `DBError`, `ParseError` map to 502 responses; wrap new error types to maintain this contract.
- **Scraper pipeline**: commits per item with rollback guard—replicate this pattern in new pipelines to avoid poisoning future inserts.
- **Prompt format**: `_parse_movie_reason_map()` strictly validates `{movie_id: reason}` JSON. Changes to prompt structure require updating `_parse_movie_reason_map()` and `tests/test_recommendation_units.py`.
- **Embeddings**: always use `text-embedding-3-small` / `vector(1536)`. If you change models, update token counting and the schema.
- **ORM queries**: showtime calendar fetches 14 days via ORM ordering—add columns carefully to avoid regressions.
- **Logging**: every LLM call is persisted verbatim in `recommendation_logs`; keep prompt/response payloads reasonably sized.
- **New DB-facing code**: prefer lightweight unit tests that mock engines/cursors over requiring a live Postgres connection.
