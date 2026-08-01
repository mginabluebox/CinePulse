# Product overview

CinePulse aggregates repertory and independent cinema schedules in New York City into a single
browsable calendar, and layers a natural-language recommender on top of it.

Two things a user can do:

1. **Browse** - a week-by-week showtime calendar across all tracked cinemas, with posters,
   ratings, genres, trailers, and direct ticket links. See [calendar-view.md](calendar-view.md).
2. **Ask** - describe a mood or taste in plain English ("something uplifting", "a mind-bender")
   and get films that are actually playing. Two flavours:
   - [search.md](search.md) - semantic search over everything currently playing, ranked by
     embedding similarity, no LLM involved.
   - [recommend.md](recommend.md) - 5 picks with a one-line reason each, chosen by an LLM from
     the top similarity candidates, presented as a swipe deck.

The differentiator over a cinema's own site is cross-venue coverage plus semantic search: the
user does not need to know a film's title to find it.

## Tracked cinemas

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

## Pages and endpoints

| Method | Route | Purpose | Doc |
|--------|-------|---------|-----|
| GET | `/` | Landing page, 7-day calendar from now, cached 300 s | [calendar-view.md](calendar-view.md) |
| GET | `/api/calendar_week/<int:week_num>` | Weeks 2+ as rendered HTML fragments, cached 300 s | [calendar-view.md](calendar-view.md) |
| POST | `/api/search_showtimes` | Semantic showtime search | [search.md](search.md) |
| GET | `/app` | Recommendation page (swipe UI) | [recommend.md](recommend.md) |
| POST | `/api/recommend_movies` | Two-stage recommendation | [recommend.md](recommend.md) |
| POST | `/api/feedback` | Record a swipe | [recommend.md](recommend.md) |

## Configuration

All configuration is environment variables, loaded from `.env` via `python-dotenv`.

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

Embeddings always go through OpenAI regardless of the chat provider, so `OPENAI_API_KEY` is
required even when running Ollama for chat.

All DB access goes through `src/database/setup_db.get_engine()`, so credentials are resolved in
exactly one place. New DB-facing code must use it rather than building its own connection string.

## Running locally

Requirements: Python 3.10+, PostgreSQL 14+ with the `pgvector` extension available, an OpenAI API
key (needed for embeddings even in Ollama mode).

### 1. Python environments

Two virtualenvs, deliberately separate: `venv` runs the app and the scraper, `venv-test` runs the
test suite.

```bash
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
python -m venv venv-test && source venv-test/bin/activate && pip install -r requirements-test.txt
```

### 2. Database

Create a database and enable pgvector:

```bash
createdb cinepulse
psql cinepulse -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

Then create the tables from the committed schema dump:

```bash
psql cinepulse -f docs/database_schema.sql
```

`docs/database_schema.sql` is a `pg_dump --schema-only` of production:
```bash
docker run --rm postgres:17 pg_dump \
  "$DB_URL" \
  --schema-only \
  --no-owner \
  --no-privileges \
  > docs/database_schema.sql
```
There is no migration tool - see
[data-model.md](data-model.md#where-the-schema-comes-from) for what that means when you add a
column.

### 3. Configuration

Copy the variables above into a `.env` at the repository root. It is gitignored and must stay that
way; it holds live database credentials and API keys.

Point `DB_*` at your local database. Every process - Flask, Scrapy, and the sync scripts - resolves
credentials through `src/database/setup_db.get_engine()`, so one `.env` covers all three.

### 4. Populate it

```bash
source venv/bin/activate

# See what the spiders would write, without touching the database
python scrapers/run_spider_and_embed.py --dry-run     # -> data/scraper/dry_run_<ts>.json

# Real run: scrape -> embed -> enrich. Calls OpenAI, OMDb, and TMDb.
python scrapers/run_spider_and_embed.py
```

An empty database serves an empty calendar, and search and recommendation return nothing until
movies have embeddings, so a full run is the fastest way to a working local app.

### 5. Run the app

```bash
export FLASK_APP=src/app.py && flask run     # or: python src/app.py
```

The full command reference is in [AGENTS.md](../AGENTS.md#commands).
