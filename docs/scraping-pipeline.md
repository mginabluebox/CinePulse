# Scraping pipeline

The offline half of the system. One entry point runs three stages in order:

```bash
python scrapers/run_spider_and_embed.py
```

| Stage | Module | Writes |
|-------|--------|--------|
| ① Scrape | `scrapers/` (Scrapy) | `movies`, `showtimes` |
| ② Embed | `src/database/sync_embeddings.py` | `movies.embedding` and its bookkeeping columns |
| ③ Enrich | `src/database/sync_enrichment.py` | OMDb/TMDb columns on `movies` |

Order matters. Embedding runs before enrichment so a newly scraped film becomes searchable and
recommendable in the same run it is scraped - candidate selection requires a non-null `embedding`,
but nothing requires enrichment.

Flags on the entry point: `--limit`, `--batch-size`, `--sleep`, `--refresh-all` (embeddings),
`--refresh-enrichment`, `--dry-run` (stage ① only, no DB writes).

In production this runs on a weekly-scheduled Fly machine; see
[architecture.md](architecture.md#deployment-topology) for the two-process deployment and why scraper
changes need an extra `fly machine update`.

## Stage 1: scrape

`CrawlerProcess` runs all four spiders in one process: `metrograph`, `film_forum`, `ifc_center`,
`angelika`. Scrapy settings live in `scrapers/settings.py` (`ROBOTSTXT_OBEY = True`, asyncio
reactor, `CinemaScraperPipeline` at priority 300).

Each spider yields **showtime-level** plain dicts. A film playing five times produces five items,
with the film-level fields repeated on each. (`scrapers/items.py` defines a Scrapy `Item` class, but
nothing imports it; it is vestigial.)

### The item contract

These are the keys `CinemaScraperPipeline` reads. Anything else in the dict is ignored.

| Key | Required | Notes |
|-----|----------|-------|
| `cinema` | yes | Falls back to `'UNKNOWN'`. Becomes `showtimes.cinema`, and drives calendar grouping, filter pills, and sweep scoping |
| `title` | yes | Raw display title; normalization happens in the pipeline |
| `show_time` | yes | `datetime`, part of the upsert conflict key |
| `show_day` | no | Weekday label, used for calendar day headings |
| `ticket_link` | no | `'sold_out'` is a sentinel, not a URL |
| `details_link` | no | Film page on the venue's site |
| `image_url` | no | Poster |
| `director1`, `director2` | no | Multi-director credits are split by the spider |
| `year` | no | Participates in movie identity |
| `runtime` | no | Minutes |
| `format` | no | Part of the conflict key; `NULL` coalesces to `'-'` on read |
| `synopsis` | no | Feeds the embedding, so it drives search and recommendation quality |
| `special_attributes`, `trailer_url` | no | Stored, not currently surfaced by the calendar |

Two spider-level conventions hold across all four:

- **Each spider defines its own `_clean()`** and applies it to every string field at yield time. It
  strips `\xa0` and trims. Title whitespace additionally passes through `_normalize_whitespace()` in
  the pipeline, but synopsis, director, and format rely solely on the spider's `_clean()`.
- **Each spider declares `cinemas = [...]`**, listing every cinema name it emits. One spider can
  serve several venues (Angelika fans out to one request per venue), and the dry-run quota logic
  depends on this list.

The parsing edge cases behind each spider, and the regression URLs that pin them, are in
[AGENTS.md](../AGENTS.md#scraper-edge-cases). Adding a spider is walked through in
[AGENTS.md](../AGENTS.md#add-a-cinema).

### `CinemaScraperPipeline`

Per item, in `scrapers/pipelines.py`:

1. Normalize the title (see [Title normalization](#title-normalization)).
2. `UPDATE movies … WHERE lower(trim(title)) = lower(trim(%s)) AND year IS NOT DISTINCT FROM %s
   RETURNING id`; on no match, `INSERT … RETURNING id`.
3. Upsert the showtime row `ON CONFLICT (movie_id, show_time, cinema, format)`.
4. `commit()` per item, with `rollback()` on `psycopg2.Error`, so one malformed item cannot poison
   subsequent inserts.
5. Record the cinema in `written_cinemas`.

The per-item commit means a single unparseable film costs one showtime rather than an entire crawl.

Movie identity is `(lower(trim(title)), year)`, backed in the database by the
`uq_idx_movies_title_year` unique index on the same expression
([data-model.md](data-model.md#constraints-and-indexes-that-actually-exist)). Two kinds of row still
slip past it, both seen in production; `scripts/dedup_movies.py` cleans up after either. What they
are and what they cost: [decisions.md](decisions.md#5-movie-identity-is-lowertrimtitle-year).

### Stale-showtime sweep

On `close_spider`, for each cinema in `written_cinemas`:

```sql
DELETE FROM showtimes
WHERE cinema = %s AND crawled_at < %s AND show_time > now()
```

where `%s` is `run_started_at`, captured in `open_spider`.

Any change to a component of the conflict key (`show_time`, `format`), or to the title/year that
resolves `movie_id`, makes the upsert insert a fresh row instead of updating, orphaning the old
one. Rows re-written this run carry `crawled_at >= run_started_at`; untouched future rows are
pruned here. Past showtimes are kept as history.

The sweep is scoped to `written_cinemas`: a cinema whose spider failed or was blocked commits
nothing, so it is never swept and its existing rows survive. `tests/test_pipeline_sweep.py` pins the
semantics.

### Dry run

```bash
python scrapers/run_spider_and_embed.py --dry-run
```

Swaps in `DryRunCollectorPipeline`, which writes nothing to the DB, caps collection at 10 movies
per cinema, and dumps items grouped by cinema and movie to `data/scraper/dry_run_<ts>.json`.

It calls the same `_prepare_item()` as the live pipeline and records both derived titles
(`_pipeline_clean_title`, `_pipeline_api_lookup`), so title-normalization changes are exercised
before any write.

The quota stops a spider by closing its engine, which cancels in-flight requests. Because one
spider can serve several cinemas, `_maybe_close()` waits until **all** of the spider's declared
`cinemas` have hit the quota - otherwise the first venue to fill would truncate the others. A
spider that omits the `cinemas` attribute still works but stops conservatively late.

Output lands in `data/scraper/`, which is gitignored working space.

## Title normalization

`src/database/title_normalization.py`, deliberately dependency-free so it imports cleanly under
both import conventions. Three levels:

| Function | Produces | Used for |
|----------|----------|----------|
| `_strip_display_suffix` | display title | stored `movies.title` |
| `_api_lookup_title` | lookup title | stored `scraped_title_normalized`, used by enrichment |
| `_normalize_for_matching` | lowercased display form | cross-cinema dedup scripts |

- `_strip_display_suffix` removes `(Open Captioning)`, `[35mm|16mm|70mm|DCP|Digital|OV]`, and a
  trailing `in 35mm`; normalizes NFKC whitespace.
- `_api_lookup_title` adds: strip a `"X presents:"` prefix (all cinemas); for Metrograph, strip an
  `"X selects"` prefix and a `"… preceded by …"` suffix; for Film Forum, extract the all-caps run
  from director-credit titles (`"Spike Lee's CROOKLYN"` → `"CROOKLYN"`) and straighten curly
  apostrophes. The Film Forum extraction is guarded by a "at least two mixed-case words" test so
  genuinely all-caps titles are not mangled.

`script.js:normalizeTitle()` mirrors `_strip_display_suffix` so the frontend can decide whether
`tmdb_original_title` differs meaningfully from the scraped title before showing it.

## Stage 2: embedding sync

`src/database/sync_embeddings.py`. Model `text-embedding-3-small` (`OPENAI_EMBED_MODEL`),
dimension **1536**, batches of 16 (`EMBED_BATCH_SIZE`).

The embedded text is deterministic:

```
Title: … | Year: … | Director: … | Synopsis: …
```

Missing parts are omitted; an empty payload is skipped. The SHA-256 of that string is stored as
`embedding_source_hash`, alongside `embedding_model` and `embedded_at`.

Selection is two-step:

1. `_fetch_movies()` selects rows where `embedding IS NULL` **or** `embedding_model` differs from
   the configured model (with `--refresh-all`, every row).
2. `_needs_embedding()` then re-checks missing embedding, model change, or hash change.

Note the consequence of step 1: a synopsis edit on a row that already has an embedding under the
current model is **not** picked up by a normal run, because it never reaches the hash check.
`--refresh-all` is the escape hatch. See
[decisions.md](decisions.md#6-embeddings-are-gated-on-a-source-hash-but-the-gate-has-a-hole).

Modes: `--refresh-all` forces re-embedding, `--dry-run` reports what would be embedded without
calling OpenAI, `--limit` / `--batch-size` / `--sleep` control throughput. Batches commit
individually; any exception rolls back and re-raises.

Changing the embedding model means changing the `vector(1536)` column type and the tiktoken
`o200k_base` counting in `llm_selector.py`, and re-embedding everything: vectors from different
models are not comparable.

## Stage 3: enrichment sync

`src/database/sync_enrichment.py`. Requires `OMDB_API_KEY` and `TMDB_API_KEY`, validated up front.

Lookup order per movie, keyed on `scraped_title_normalized`:

1. **OMDb** for `imdb_id` and the ratings (`imdb_rating`, `imdb_votes`, `omdb_rt_score`,
   `omdb_metacritic_score`).
2. **TMDb** `/find` on the IMDb ID, falling back to `/search/movie`.
3. **TMDb** `/movie/{id}` with `append_to_response=videos,translations` for genres, poster,
   runtime, tagline, overview, languages, collection, release date, trailer, and Chinese title.

Fallback ladder for edition-suffixed titles (`"… Director's Cut"`): retry without the year, then
with the suffix stripped. The trailer picks an official YouTube trailer when available; the Chinese
title prefers CN, then TW, then HK.

Default scope is movies with a future showtime that are unenriched, have no release date, or were
released within the last 30 days, ordered `enriched_at` nulls first. The release-date window is
what keeps ratings fresh on new releases while leaving settled catalogue titles alone.

Modes: `--apply` (the default is dry-run), `--refresh-all`, `--refresh-count N` (backfill
unenriched rows DB-wide, ignoring the future-showtime filter), `--backfill-titles` (recompute
`scraped_title_normalized` with no API calls - rows missing it, or every row when combined with
`--refresh-all`), `--limit`, `--sleep` (default 0.1 s between calls).
