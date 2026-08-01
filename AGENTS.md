# AGENTS.md

Working instructions for AI coding agents and maintainers in this repository.
`CLAUDE.md` and `.github/copilot-instructions.md` both point here; this is the only copy.

**This file is about doing work.** For understanding the system - what it does, why it is built
this way, how data flows, how to extend it - read [docs/](docs/README.md). Do not duplicate that
material here, and do not describe architecture here: a second copy will drift, and a stale copy is
worse than a link.

To change the documentation itself, run the **`doc-update` skill**
(`.claude/skills/doc-update/`). It owns the ownership map, the audit process, and the review gate.

## Orientation

CinePulse scrapes New York repertory cinema schedules into Postgres with pgvector, and serves a
showtime calendar, semantic search, and an LLM-backed recommender from a Flask app. Ingestion runs
weekly and offline; the web app only reads. The database is the only contract between them.

Start with [docs/overview.md](docs/overview.md) and [docs/architecture.md](docs/architecture.md).
Before changing anything non-trivial, read [docs/decisions.md](docs/decisions.md) - several things
that look wrong are deliberate.

---

## Setup

Two virtualenvs, kept separate on purpose:

```bash
source venv/bin/activate        # app + scrapers
source venv-test/bin/activate   # tests only
```

Always activate one before running anything. Configuration is a gitignored `.env` at the repository
root holding live database credentials and API keys; never print it, commit it, or paste its
contents into a response. Full variable list: [docs/overview.md](docs/overview.md#configuration).

---

## Commands

**Run the app**
```bash
export FLASK_APP=src/app.py && flask run     # or: python src/app.py
```

**Tests** (see [Before you merge](#before-you-merge))
```bash
source venv-test/bin/activate
pytest tests/                                # full mocked suite
pytest tests/test_recommendation_helpers.py  # one file
pytest -k parse_movie_reason                 # one test by name
```

**Scrapers**
```bash
python scrapers/run_spider_and_embed.py --dry-run   # $0, no DB writes -> data/scraper/
python scrapers/run_spider_and_embed.py             # scrape -> embed -> enrich, writes + spends
scrapy crawl film_forum                             # one spider, writes to the DB
scrapy crawl film_forum -s TEST_MODE=1              # writes under TEST_<CINEMA> names
```

**Embeddings** (`$` = spends money)
```bash
python src/database/sync_embeddings.py --dry-run    # report only
python src/database/sync_embeddings.py              # $ embed new/changed rows
python src/database/sync_embeddings.py --refresh-all # $$ re-embed the entire catalogue
```

**Enrichment** (dry-run by default)
```bash
python src/database/sync_enrichment.py              # report only
python src/database/sync_enrichment.py --apply      # write
python src/database/sync_enrichment.py --backfill-titles  # no API calls
```

**Maintenance scripts**
```bash
python scripts/dedup_movies.py        # clean up duplicate movie rows
python scripts/clear_enrichment.py    # reset enrichment columns
```

**Smoke-test the API**
```bash
curl -s localhost:5000/api/search_showtimes \
  -H 'Content-Type: application/json' -d '{"query":"slow-burn noir"}' | head -c 400

curl -s localhost:5000/api/recommend_movies \
  -H 'Content-Type: application/json' \
  -d '{"preference":"something uplifting","session_token":"dev-local"}' | head -c 400
```

---

## Workflow for a change

1. **Read the relevant doc first.** [docs/](docs/README.md) has a page per component and
   [Multi-file changes](#multi-file-changes) below covers the changes that cross several files.
2. **Reproduce before fixing.** For a bug, reproduce it end to end the way a user hits it - through
   the route or a real crawl - before changing code. A fix for a bug you never reproduced is a
   guess.
3. **Branch.** Never commit directly to `main`; pushing to `main` deploys to production
   (see [Safety constraints](#safety-constraints)).
4. **Change the code**, matching the surrounding style. Check
   [Files that need special handling](#files-that-need-special-handling) for anything that requires
   a paired edit.
5. **Dry-run anything that touches ingestion.** `--dry-run` exercises the same normalization code as
   the live path and writes nothing.
6. **Test.** See [Before you merge](#before-you-merge).
7. **Update the docs in the same change.** A one-line correction, edit it in place. Anything larger -
   a new feature, a restructure, docs that have gone stale - run the **`doc-update` skill**, which
   audits first and reports before editing. New scraper landmines also go in
   [scraper edge cases](#scraper-edge-cases) below, with a regression URL.
8. **Report honestly.** If tests fail, say so with the output. If part of the task was skipped, say
   which part and why.

---

## Before you merge

```bash
source venv-test/bin/activate && pytest tests/
```

Must be green. This is the whole gate, and it is a local one:

- **CI does not run tests.** `.github/workflows/fly-deploy.yml` checks out, installs flyctl, and
  deploys. Nothing else. A green pipeline means the image built.
- **There is no linter or formatter configured.** No ruff, black, flake8, or pre-commit. Match the
  style of the file you are editing; do not reformat unrelated lines.
- **`pytest tests/` excludes billed tests** via `addopts = -m "not integration"` in `pytest.ini`.
  Leave that default alone.

Add tests with the change: DB-facing code gets lightweight unit tests that mock engines and cursors
rather than requiring live Postgres; spider parsing gets pinned HTML fixtures like
`tests/test_film_forum_spider.py`.

---

## Safety constraints

Read this section before running anything that writes, deploys, or calls an external API.

### Pushing to `main` deploys to production

`.github/workflows/fly-deploy.yml` runs `flyctl deploy --remote-only` on **every push to `main`**,
with no test gate and no staging environment. Work on a branch. Do not push to `main` unless the
intent is to ship, and never as a way to "trigger CI".

### The test suite can reach the production database

`tests/conftest.py` loads the real `.env`. Its own comment says so: a missed monkeypatch "would
otherwise hit the production DB". The only guard is an autouse fixture stubbing
`insert_recommendation_feedback`. Nothing else is protected.

Therefore: any new test that exercises DB-facing code **must** mock the engine, session, or cursor
explicitly. Never add a test that calls a real query function and relies on it "probably" not
writing. If you add a second write path from the app, extend the autouse guard in `conftest.py`.

### Commands that spend money

| Command | Cost |
|---------|------|
| `pytest -m integration` | Live OpenAI calls, billed. Never run it as part of a routine test pass |
| `sync_embeddings.py` with no flags | One embedding call per new or changed movie |
| `sync_embeddings.py --refresh-all` | Re-embeds the **entire** catalogue. Confirm with the user first |
| `sync_enrichment.py --apply` | OMDb + TMDb calls per movie |
| `run_spider_and_embed.py` with no flags | All of the above, plus writes |
| Hitting `/api/recommend_movies` | One embedding call plus one chat completion, and it consumes the daily quota of 35 |

`sync_enrichment.py` defaults to dry-run. `sync_embeddings.py` and `run_spider_and_embed.py` **do
not** - they write and spend unless given `--dry-run`.

**A new route that calls a chat LLM must carry a rate-limit check**, the way
`/api/recommend_movies` does. The endpoints are public and unauthenticated, so that check is the
only thing between a new route and an unbounded bill.

### Commands that delete data

The scraper's `close_spider` issues `DELETE FROM showtimes` for every cinema that committed a write
this run. It is scoped to future showtimes older than the run start, and scoped to
`written_cinemas` so a failed spider never wipes a venue. Preserve both scopes when touching
`scrapers/pipelines.py`; `tests/test_pipeline_sweep.py` pins them.

`scripts/dedup_movies.py` and `scripts/clear_enrichment.py` mutate existing rows. Read them before
running them.

### Testing against real data

Use `--dry-run` for spider work. If you must write, `-s TEST_MODE=1` prefixes the cinema name with
`TEST_`, which keeps rows out of the calendar and out of the sweep's blast radius for real venues.
Clean up afterwards.

---

## Repository conventions

- **Two import conventions coexist.** The web app runs with `src/` on the path
  (`from database.queries import …`); scrapers and standalone scripts run from the repository root
  (`from src.database.queries import …`). Match whichever half your file lives in.
  `tests/conftest.py` puts both on `sys.path`.
- **`src/database/title_normalization.py` must stay dependency-free.** It is imported from both
  sides; adding a Flask, SQLAlchemy, or Scrapy import breaks the scraper.
- **All DB access goes through `src/database/setup_db.get_engine()`.** Never build a connection
  string or read `DB_*` directly.
- **Wrap errors that cross an API boundary** into `LLMError`, `DBError`, or `ParseError`. Those map
  to 502; anything else becomes an opaque 500. `tests/test_api_error_mapping.py` pins this.
- **New pipelines commit per item with a rollback guard**, so one malformed item cannot poison
  subsequent inserts.
- **Embeddings are `text-embedding-3-small` / `vector(1536)`.** Changing the model means changing
  the column type, the tiktoken `o200k_base` counting in `llm_selector.py`, and re-embedding
  everything.
- **Keep LLM prompt and response payloads reasonably sized** - every call is stored verbatim in
  `recommendation_logs`.
- **`tests/` is committed unit tests only.** `data/`, `notebooks/`, and `scripts/` working output is
  gitignored; scraper crawl dumps go to `data/scraper/`, never into `tests/`.
- **`docs/database_schema.sql` is the authoritative schema**, not `models.py`. There is no migration
  tool: adding a column means altering the database by hand, updating `models.py`, **and**
  regenerating the dump with `pg_dump --schema-only`. See
  [docs/data-model.md](docs/data-model.md#where-the-schema-comes-from).
- **UI work follows the existing design system**: only the `:root` CSS variables, no new colours;
  Space Grotesk for headings and labels, system UI for body; accent red for primary actions, hover,
  and active indicators only, never decoration; new components match existing patterns
  (`.cp-cinema-filter-btn`, `.cp-show-more-btn`, `.cp-details-arrow`). The rationale is in
  [docs/frontend.md](docs/frontend.md#design-system).
- **Never commit `.env`** or echo secrets into output.

---

## Multi-file changes

Two changes cross enough files that the usual failure is a layer that silently drops the new data.
Both assume the rules in [Scraper edge cases](#scraper-edge-cases) and
[Paired implementations](#paired-implementations) below.

### Add a cinema

Four spiders currently feed six cinemas. A fifth touches five files.

1. **Write** `scrapers/spiders/<venue>_spider.py` after the shape of the existing four. It needs
   `name`, `cinemas = [...]`, `start_urls`, and its own `_clean()`. Pick the cinema name once and
   use it verbatim everywhere - it is the identity the system groups, filters, and sweeps by.
2. **Yield** one plain dict per screening, per
   [the item contract](docs/scraping-pipeline.md#the-item-contract).
3. **Register** it in `scrapers/run_spider_and_embed.py` in **both** `run_spider()` and
   `_run_dry_spiders()`. Missing the second means `--dry-run` never exercises the new spider.
4. **Handle house title style.** If the venue writes titles as "Someone Presents: FILM" or
   "FILM in 35mm", add a branch to `_api_lookup_title()` keyed on the cinema name
   ([title normalization](docs/scraping-pipeline.md#title-normalization)). Get this wrong and the
   film silently never gets ratings, genres, or a poster - enrichment looks it up by that title.
5. **Verify and document.** Dry-run, then inspect the dump for the new cinema: `title` against
   `_pipeline_clean_title` and `_pipeline_api_lookup`, showtimes with correct AM/PM, synopsis
   starting at a sentence boundary. Then add a row to
   [docs/overview.md](docs/overview.md#tracked-cinemas), pin the tricky pages as fixtures the way
   `tests/test_film_forum_spider.py` does, and record any landmine below with a regression URL.

### Add a field end-to-end

Say `certification` from the spider through to the calendar. Eight touchpoints, in dependency order:

| # | File | Change |
|---|------|--------|
| 1 | `scrapers/spiders/*.py` | Parse it, `_clean()` it, add it to the yielded dict |
| 2 | Database | `ALTER TABLE` by hand, then regenerate `docs/database_schema.sql`. No migration tool; see [docs/data-model.md](docs/data-model.md#adding-a-column) |
| 3 | `src/database/models.py` | Add the `Column(...)` so ORM reads see it |
| 4 | `scrapers/pipelines.py` | Add to the `INSERT` list, the `VALUES` tuple, **and** `ON CONFLICT DO UPDATE SET` |
| 5 | `src/database/queries.py` | Add to the `session.query(...)` projection **and** the returned dict |
| 6 | `src/app.py` | For the calendar, add it to the film dict in `build_calendar()` |
| 7 | `src/bots/get_recommendation.py` | For search or recommendations, add it to both result payloads |
| 8 | `_week_panels.html` **and** `script.js` | Render it in the Jinja macro and its JS mirror |

Steps 4 and 8 are where fields get lost. In `INSERT` but not `ON CONFLICT DO UPDATE` looks right on
a fresh row and goes stale on every later crawl. In Jinja but not `script.js` appears on the
calendar and vanishes in search results.

If the field should influence ranking it also goes into `_build_embedding_input()` in
`sync_embeddings.py` - which changes the source hash for every movie, so budget a full catalogue
re-embed with `--refresh-all`.

---

## Files that need special handling

### Paired implementations

The same logic exists server-side and client-side. **Editing one without the other silently
diverges the calendar from search results.** Full table:
[docs/frontend.md](docs/frontend.md#mirrored-implementations).

| Change this | Also change this |
|-------------|------------------|
| `render_film_banner()` in `_week_panels.html` | `renderFilmBanner()` in `script.js` |
| `_strip_display_suffix()` in `title_normalization.py` | `normalizeTitle()` in `script.js` |
| `parse_showtime_mins()` / `showtime_period()` in `app.py` | `_stMins()` / `_stPeriod()` in `script.js` |
| Format suppression list in `_week_panels.html` | `_fmtTag()` in `script.js` |
| `build_movie_prompt()` output format | `_parse_movie_reason_map()` **and** `tests/test_recommendation_units.py` |
| A new column in `pipelines.py` `INSERT` | The `ON CONFLICT DO UPDATE SET` clause in the same statement |

### Individual files

- **`scrapers/pipelines.py`** - the stale sweep and the per-item commit both have safety properties
  described above. Do not simplify either.
- **`src/database/models.py`** - a partial view of the schema, not the schema. It declares no
  constraints or indexes, and its commented-out `uq_movie_title_year` is stale: production carries a
  unique index on `(lower(trim(title)), year)`. Check `docs/database_schema.sql` before reasoning
  about what the database enforces.
- **`src/bots/get_recommendation.py`** - stage 1 passes `start_date=None` on purpose. Passing the
  app's ET-formatted string makes Postgres read it as UTC, a four-hour offset that lets
  already-started screenings through as candidates.
- **`src/database/queries.py`** - the calendar query's projection and ordering are what
  `build_calendar()` relies on. Add columns carefully.
- **`scrapers/items.py`** - vestigial. Spiders yield plain dicts; nothing imports the `Item` class.

---

## Scraper edge cases

Every rule below traces to a real bug. They look like over-complication; do not simplify them away.
The Film Forum cases are pinned as HTML fixtures in `tests/test_film_forum_spider.py`. The IFC ones
have no test coverage yet, so verify those by hand against the regression URLs.

How the pipeline works is in [docs/scraping-pipeline.md](docs/scraping-pipeline.md); how to add a
spider is in [Add a cinema](#add-a-cinema).

### All spiders

- **`_clean()` every string field at yield time.** Each spider defines its own `_clean()` that
  strips `\xa0` and trims. Wrap any new string field you add to a yield dict. Title whitespace
  additionally goes through `_normalize_whitespace()` in `pipelines._prepare_item`, but synopsis,
  director, and format rely solely on the spider's `_clean()`.
  **Why:** movies are matched on `lower(trim(title))` + `year IS NOT DISTINCT FROM`, and Postgres
  `trim()` does not strip `\xa0`, so one non-breaking space - or a `NULL` year - silently creates a
  duplicate movie row. Both have happened (Film Forum REUNION, DAYS AND NIGHTS IN THE FOREST).
- **The stale-showtime sweep is scoped to `written_cinemas`.** `close_spider` only deletes future
  showtimes for cinemas that committed at least one item this run, so a spider that fails or gets
  blocked cannot wipe that cinema's schedule. Preserve this when touching `pipelines.py`.
- **Every spider must declare `cinemas = [...]`**, listing each cinema name it emits.
  **Why:** `--dry-run` stops a spider by closing its engine, which cancels in-flight requests, and
  one spider can serve several venues. Omitting the attribute makes a multi-venue spider truncate
  all but the first venue. Mechanics:
  [docs/scraping-pipeline.md](docs/scraping-pipeline.md#dry-run).

### IFC Center

- Detail pages come in two shapes: **with** and **without** `<ul class="schedule-list">`. Both need
  handling - before the fallback XPath existed, the no-schedule-list variant yielded
  `synopsis = None`.
- Anchor to `schedule-list[last()]`. The first one is often a "Special Events" Q&A block rather than
  the ticket block.
- `<ul class="schedule-list">` is ticket-buying UI and **never** belongs in the synopsis. But `<p>`
  event/Q&A paragraphs in the synopsis zone ("Thursday, April 9 at 6:30: Q&A with...") **do** belong.
  A weekday-prefix filter was deliberately removed - do not reintroduce it.
- The `Director` metadata field is one comma-separated string; split it into `director1` /
  `director2`.

### Film Forum

- Extract synopsis text from the **full subtree** (`::text` / `_text_with_br`), never `./text()`.
  Opening sentences routinely sit inside `<em>` / `<strong>` / `<a>` children, so direct-text-only
  extraction starts the synopsis mid-sentence.
- Walk `div.copy`'s direct children and **break at the first `<h3>`**. `css('div.copy p')` grabs
  every `<p>` in document order, dragging in review pull-quotes that follow `<h3>Reviews</h3>`.
- **Pattern B pages put the metadata `<strong>` block and the prose in the same `<p>`**, split by
  `<br><br>`. Never skip a whole paragraph just because it matches "Directed by" - that drops the
  synopsis entirely.
- The metadata block (year / director / runtime) **intentionally remains** in the stored synopsis.
  That is source formatting, not a parsing bug - do not "fix" it.
- Year extraction must be an unanchored `re.search(r'\b((?:19|20)\d{2})\b', line)`. The metadata line
  reads `India, 1970` - country first, year second - so an anchored `^(\d{4})` never matches.
- Showtimes carry no AM/PM. Heuristic in `_parse_film_forum_time`: hours 1-9 are PM, 10 and 11 are
  AM, 12 stays noon.

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

---

## Deployment runbook

Fly.io app `cinepulse`, region `sjc`. Two processes share one image but have separate lifecycles;
the topology and its rationale are in
[docs/architecture.md](docs/architecture.md#deployment-topology).

Pushing to `main` deploys the web app automatically. The commands below are for manual or
out-of-band deploys.

**App-only changes**
```bash
fly deploy --depot=false
```
The scheduled scraper machine is pinned to the image digest it was created with and is unaffected.

**Scraper code changes** need a second step - after `fly deploy`, re-point the machine:
```bash
fly machines list --app cinepulse
fly machine update <machine-id> --image registry.fly.io/cinepulse:latest --app cinepulse
```
Skipping this is the most common deployment mistake in this project: the code ships, the weekly job
keeps running the old image, and nothing reports it.

**Smoke-test an image** as a one-off machine (no `--schedule`) before scheduling it:
```bash
fly machine run registry.fly.io/cinepulse:latest \
  --app cinepulse \
  --command "python /app/scrapers/run_spider_and_embed.py" \
  --region sjc --vm-memory 256

fly logs --app cinepulse --machine <machine-id>
```

**Recreate the scheduled machine** if it is ever deleted:
```bash
fly machine run registry.fly.io/cinepulse:latest \
  --app cinepulse \
  --schedule weekly \
  --command "python /app/scrapers/run_spider_and_embed.py" \
  --region sjc \
  --vm-memory 256
```
