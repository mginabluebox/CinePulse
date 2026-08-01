# Data model

PostgreSQL with the pgvector extension. Four tables: `movies` and `showtimes` are written by the
ingestion pipeline and read by the web app; `recommendation_logs` and `recommendation_feedback`
are written by the web app only.

`movies` and `showtimes` are declared as SQLAlchemy models in `src/database/models.py`. The two
log tables are written through raw parameterized SQL in `src/database/queries.py`.

> **`models.py` is not the source of truth for the schema** -
> [`database_schema.sql`](database_schema.sql) is. See
> [Where the schema comes from](#where-the-schema-comes-from) before creating a database or adding
> a column.

## `movies` - one row per distinct film

Identity is `(lower(trim(title)), year)`, resolved by the scraper pipeline (see
[scraping-pipeline.md](scraping-pipeline.md)).

| Group | Columns |
|-------|---------|
| Identity | `id`, `title`, `year`, `created_at`, `updated_at` |
| Scraped | `scraped_synopsis`, `scraped_director1`, `scraped_cinema`, `scraped_image_url`, `scraped_details_link`, `scraped_title_normalized` |
| Embedding | `embedding vector(1536)`, `embedding_model`, `embedding_source_hash`, `embedded_at` |
| External IDs | `imdb_id`, `tmdb_id` |
| OMDb ratings | `imdb_rating`, `imdb_votes`, `omdb_rt_score`, `omdb_metacritic_score` |
| TMDb metadata | `tmdb_original_title`, `tmdb_genres[]`, `tmdb_origin_countries[]`, `tmdb_original_language`, `tmdb_spoken_languages[]`, `tmdb_tagline`, `tmdb_overview`, `tmdb_runtime`, `tmdb_collection_name`, `tmdb_poster_url`, `tmdb_release_date`, `tmdb_trailer_url`, `tmdb_title_zh` |
| Bookkeeping | `enriched_at` |

`scraped_title_normalized` holds the API-lookup form of the title (see
[scraping-pipeline.md](scraping-pipeline.md#title-normalization)) and is what enrichment queries
OMDb/TMDb with. The UI also compares it against `tmdb_original_title` to decide whether showing
the original title adds information.

## `showtimes` - one row per screening

Uniqueness is enforced by `uq_showtimes_movie_time_cinema_format`
([definition](#constraints-and-indexes-that-actually-exist)). It is the `ON CONFLICT` key for the
pipeline upsert, so changing any part of it causes an insert rather than an update - which is what
the stale sweep cleans up after.

| Group | Columns |
|-------|---------|
| Screening | `id`, `crawled_at`, `show_time`, `show_day`, `cinema`, `ticket_link`, `details_link`, `image_url`, `special_attributes`, `trailer_url`, `format` |
| Denormalized film fields | `title`, `director1`, `director2`, `year`, `runtime`, `synopsis` |
| FK | `movie_id → movies.id` |

Film-level fields are duplicated onto showtimes; the movie row remains the canonical record for
embeddings and enrichment. Why they are duplicated, and what the two copies cost:
[decisions.md](decisions.md#4-film-level-fields-are-duplicated-onto-showtimes).

`ticket_link = 'sold_out'` is a sentinel, not a URL. The recommender excludes sold-out showtimes;
the calendar renders them as a disabled chip.

`crawled_at` is the timestamp of the crawl that last wrote the row, and is what the stale sweep
compares against the run start time.

## `recommendation_logs`

Every LLM call, success or failure, written by `call_llm()`:

`queried_at`, `api_name`, `model_name`, `prompt_num_token`, `prompt`, `response`,
`error_code` (0 = success, 1 = failure), `run_id`, `session_token`.

Doubles as the rate-limiting ledger: `check_rate_limits()` counts rows with `error_code = 0` since
`date_trunc('day', now())`, globally and per `session_token`.

Prompts and responses are stored verbatim, so keep payloads reasonably sized when changing the
prompt.

## `recommendation_feedback`

Swipe outcomes, written by `POST /api/feedback`:

`run_id`, `session_token`, `movie_id`, `liked`, `decision_ms`, `similarity`, `title`, `year`,
`created_at`.

`run_id` is a fresh UUID minted per recommendation request and ties a feedback row back to the LLM
call that produced the card. `similarity` is the stage-1 cosine score, carried through the API
response and posted back by the client, so ranking quality can be evaluated offline against actual
likes and dislikes.

## Where the schema comes from

**[`database_schema.sql`](database_schema.sql) is authoritative.** It is a `pg_dump --schema-only`
of production (PostgreSQL 17.6, hosted on Supabase), so it captures the real column types,
constraints, and indexes. Regenerate it after any schema change.

The application tables are in the `public` schema. The dump also carries Supabase's `auth`,
`storage`, `realtime`, `graphql`, and `vault` schemas, which the application never touches; ignore
them. It contains no data and no secrets, only DDL.

There is still **no migration tool** - no Alembic, no migration directory, and nothing calls
`Base.metadata.create_all()`. What that costs:
[decisions.md](decisions.md#8-schema-is-a-committed-dump-not-migrations).

### `models.py` is a partial view, not the schema

`src/database/models.py` declares columns for `movies` and `showtimes` and nothing else. It does not
declare any of the constraints or indexes the code depends on, and it has drifted from production in
one visible way: `uq_movie_title_year` is commented out there, while production **does** carry an
equivalent unique index. Read the dump, not the models, when correctness matters.

### Constraints and indexes that actually exist

| Object | Definition | Why it matters |
|--------|-----------|----------------|
| `uq_showtimes_movie_time_cinema_format` | `UNIQUE (movie_id, show_time, cinema, format)` on `showtimes` | The `ON CONFLICT` target for the pipeline upsert. Without it, every crawl inserts duplicate showtimes |
| `uq_idx_movies_title_year` | `UNIQUE INDEX ON movies (lower(trim(title)), year)` | Enforces movie identity in the database, matching the pipeline's lookup key exactly |
| `fkey_showtimes_movie_id` | `FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE RESTRICT` | A movie cannot be deleted while showtimes reference it, so dedup scripts must repoint showtimes first |
| `idx_showtimes_movie_id` | btree on `showtimes(movie_id)` | Showtime hydration by movie id |
| `idx_recommendation_logs_queried_at` | btree on `recommendation_logs(queried_at DESC)` | Rate-limit counting by day |
| `idx_recommendation_logs_api_name` | btree on `recommendation_logs(api_name)` | Log analysis |

**There is no index on `movies.embedding`.** The column is `vector(1536)` and pgvector is installed,
but no ivfflat or hnsw index exists. Why that is, and what it means for moving ranking into SQL, is
[decisions.md](decisions.md#2-similarity-is-computed-in-python-not-in-pgvector).

`uq_idx_movies_title_year` treats `NULL` years as distinct, so two rows with the same title and
`year IS NULL` can both exist. What that costs, and the second way rows slip past the index, is
[decisions.md](decisions.md#5-movie-identity-is-lowertrimtitle-year).

### Adding a column

1. `ALTER TABLE` against production and each local database. There is no tooling for this.
2. Add the matching `Column(...)` to `models.py` so ORM reads can project it.
3. Regenerate `database_schema.sql`:
   ```bash
   docker run --rm postgres:17 pg_dump "$DB_URL" \
     --schema-only --no-owner --no-privileges > docs/database_schema.sql
   ```
4. Wire it through the layers that need it: see
   [AGENTS.md](../AGENTS.md#add-a-field-end-to-end).

Nothing verifies that steps 1 and 2 agree. A column in `models.py` that is missing from the database
fails at query time; the reverse is invisible until someone needs the field.
