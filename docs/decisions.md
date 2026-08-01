# Design decisions

Why the system is shaped the way it is. Each entry states the decision, the alternative that was
not taken, and the cost of living with it. Where a decision was made implicitly or by accretion
rather than deliberately, this document says so rather than inventing a rationale.

**This is the only doc that evaluates.** The rest of `docs/` describes how the system works and
stays neutral; every judgment, tradeoff, limitation, and "we would do this differently" belongs
here. Each entry links to the descriptive doc for the mechanism rather than restating it, and the
known limitations are collected in [what we would change next](#what-we-would-change-next).

---

## 1. The database is the only contract between ingestion and serving

**Decision.** Ingestion runs offline on a weekly cron and only writes; the web app only reads. No
queue, no RPC, no shared process. Mechanics:
[architecture.md](architecture.md).

**Alternative.** Trigger ingestion from the app, or run both halves in one process.

**Why.** Three properties fall out of the split for free:

- A failed scrape degrades to stale data, not missing data. Nothing fails toward *wrong* data, which
  is the property the stale sweep's `written_cinemas` scoping exists to protect.
- The two halves scale independently. Neither sizing constrains the other.
- The expensive work, embedding the whole catalogue, is amortised offline, so a recommendation costs
  one embed call plus one LLM call at request time.

**Cost.** Freshness is bounded by the cron interval: a film added mid-week is invisible until the
next run, and one scraped but not yet embedded is invisible to both search and recommendation.
Deploys are split too, and the scheduled machine needs a separate `fly machine update` that is easy
to forget and reports nothing when skipped.

---

## 2. Similarity is computed in Python, not in pgvector

**Decision.** Candidates are scored with a Python cosine loop in the app process, not in the
database. Mechanics: [recommend.md](recommend.md#two-stages), [search.md](search.md#ranking).

**Alternative.** `ORDER BY embedding <=> :query_vec LIMIT 30` in SQL, using the pgvector index.

**Why.** Honest answer: this was the straightforward thing to write, and at the current catalogue
size (a few hundred films with future showtimes) it is fast enough that no one has needed to change
it. It is not a considered choice in favour of Python.

**Cost.** Every request transfers the full candidate set over the wire and scores it linearly. This
is the first thing to change if the catalogue grows by an order of magnitude, or if coverage expands
beyond New York.

Note that the move is slightly larger than "rewrite the query": pgvector is installed and
`movies.embedding` is a `vector(1536)` column, but **no ivfflat or hnsw index exists on it**. A
`<=>` ordering without an index is still a sequential scan, so switching means creating the index
too, and choosing its parameters. `queries.py` gains an ordered, limited query;
`get_recommendation.py` loses its scoring loop.

---

## 3. Recommendation re-ranks with an LLM; search does not

**Decision.** [Recommendation](recommend.md) runs cosine retrieval and then an LLM re-rank with
reasons. [Search](search.md) stops after retrieval.

**Why.** The two answer different questions. Search answers "what here is about X", which
similarity does well on its own. Recommendation answers "what should *I* watch tonight", which
needs judgment that cosine distance cannot express: tone, intent, and the one-line reason that
makes a pick feel addressed to the user rather than retrieved for them.

Keeping search LLM-free is what makes it free to run and instant, so it can sit inline on the
landing page with no rate limit. Recommendation carries the cost and therefore the rate limit.

**Cost.** Recommendation is the only request-time chat-LLM dependency, and the only endpoint that
can fail because a third party is down or slow, under a 60 s gunicorn timeout.

---

## 4. Film-level fields are duplicated onto `showtimes`

**Decision.** `title`, `director1/2`, `year`, `runtime`, `synopsis` live on both `movies` and
`showtimes`.

**Why.** The calendar renders a week of screenings from a single query with no join fan-out
concerns, and the scraper can write a showtime row before or independently of resolving film-level
metadata.

**Cost.** The copies drift. The calendar reads the showtime copy, the recommender reads the movie
copy, so the same film can present differently on two pages. There is no reconciliation pass. In
practice this is masked because both are written by the same pipeline run.

---

## 5. Movie identity is `(lower(trim(title)), year)`

**Decision.** The pipeline does UPDATE-then-INSERT on that key, and production backs it with
`uq_idx_movies_title_year`, a unique index on `(lower(trim(title)), year)`.

**Why.** Source sites do not expose stable film IDs, and titles arrive in inconsistent display
forms, so the key has to be a normalized title. Normalizing in the index expression rather than in a
stored column means the database enforces exactly what the pipeline queries.

**Cost.** Two holes remain:

- **`NULL` years are not deduplicated.** A unique index treats NULLs as distinct, so two rows with
  the same title and no year can both exist. This is the duplicate case actually seen in production,
  and why the spiders work hard to extract a year.
- **Normalization happens before the key is computed.** A stray `\xa0` survives `trim()` and
  produces a title the index considers different, so the guard only holds if the spider's `_clean()`
  ran. `scripts/dedup_movies.py` exists to clean up after the cases that slipped through.

`models.py` still has its `uq_movie_title_year` declaration commented out, which is stale relative
to production rather than an accurate reflection of it. See
[data-model.md](data-model.md#modelspy-is-a-partial-view-not-the-schema).

---

## 6. Embeddings are gated on a source hash, but the gate has a hole

**Decision.** Rows are re-embedded only when a hash of the exact embedded text changes, so reruns
are idempotent and cheap. Mechanics:
[scraping-pipeline.md](scraping-pipeline.md#stage-2-embedding-sync).

**Cost.** The SQL prefilter never surfaces rows whose content changed under an unchanged model, so
the hash check cannot see them. The gate therefore prevents redundant work but does not detect
content drift, and `--refresh-all` is the only way to pick up edited synopses. Worth fixing by
widening the prefilter rather than by dropping the hash.

---

## 7. Search applies a per-cinema quota instead of a global ranking

**Decision.** Search fills results under a per-cinema quota rather than taking the global top N.
Mechanics: [search.md](search.md#the-per-cinema-quota).

**Why.** A pure global ranking lets one venue dominate. Cinemas differ in catalogue size and, more
importantly, in how richly they write synopses, and synopsis text is most of the embedded content.
Without the quota, the venue with the most verbose programme notes wins the top of every query
regardless of actual relevance.

**Cost.** Results are no longer a pure ranking. A well-matching film at a venue that has exhausted
its quota is dropped from results entirely rather than demoted, which is surprising if you assume
the list is ordered by score alone.

---

## 8. Schema is a committed dump, not migrations

**Decision.** `docs/database_schema.sql` is a `pg_dump --schema-only` of production, refreshed by
hand. There is no Alembic, no migration directory, and nothing calls `Base.metadata.create_all()`.

**Why.** Accretion, not choice. The schema was built by hand early and never retrofitted with
tooling. Committing the dump is a cheap partial fix: it makes the real schema readable and lets a
fresh database be stood up, without pretending to be version control for the schema.

**Cost.** A dump is a snapshot, not a history. It records what production looks like now, not how it
got there, and nothing enforces that it is current - a column added to production without
regenerating the dump leaves it silently wrong. `models.py` remains a partial and already-drifted
view (it omits every constraint and index, and its commented-out unique constraint contradicts the
index production actually has). No test catches any of this. Alembic remains the real fix.

---

## 9. Rate limiting is per-browser and cost-shaped

**Decision.** A daily global cap and a per-browser cap, counted from successful LLM calls.
Mechanics: [recommend.md](recommend.md#rate-limiting).

**Why.** The app is a personal project on a small budget with a public, unauthenticated endpoint
that spends money per request. The limits exist to bound a bad day, not to be fair. The specific
numbers are a budget judgment, not a measured figure.

**Cost.** The session token is a `localStorage` UUID: it identifies a browser, not a person, and
clearing it resets the quota. It is a cost guardrail and explicitly not a security control. Counting
only successes means a failed LLM call does not burn quota, which is the right trade but does let a
persistently failing provider be retried indefinitely.

---

## 10. The frontend is server-rendered Jinja plus vanilla JS

**Decision.** No framework, no build step, no bundler. Week 2+ of the calendar arrives as
pre-rendered HTML fragments, not JSON.

**Why.** The page is mostly static content with a few interactions, so a framework would add a build
step and a dependency tree to solve a problem the app does not have. Serving later weeks as HTML
from the macros the server already used means injected markup cannot drift from server-rendered
markup, which removes a whole class of bug rather than trading it for another.

**Cost.** Client-rendered surfaces (search results, swipe summary) need a JavaScript reimplementation
of the same components, so several functions in `script.js` mirror Jinja macros and Python helpers
and must be edited in pairs. See [frontend.md](frontend.md#mirrored-implementations).

---

## 11. Caching is in-process and per-machine

**Decision.** Flask `SimpleCache` with a 300 s timeout on the two calendar routes. Mechanics:
[architecture.md](architecture.md#caching).

**Why.** The calendar is identical for every visitor and changes once a week, so a short in-process
cache removes almost all repeat query cost for one line of configuration.

**Cost.** With `workers = 1` and machines that stop when idle, the cache is per-machine and cold on
every wake, so the first request after an idle period always pays full query cost. It also cannot be
invalidated after a scrape: fresh data waits out the 300 s. Both stop being acceptable at more than
one machine, at which point this needs to become a shared cache.

---

## What we would change next

Each item is the cost of a decision above, in rough order of how soon it will matter.

| Change | Because |
|--------|---------|
| pgvector `<=>` ordering plus an ivfflat or hnsw index | #2. In-process scoring grows linearly with the catalogue |
| Adopt a migration tool and reconcile `models.py` with the schema | #8. The dump is a snapshot, and `models.py` has already drifted |
| Widen the embedding prefilter so content changes are detected | #6. Edited synopses are invisible without `--refresh-all` |
| Backfill years and repair `NULL`-year duplicates | #5. The unique index cannot dedupe undated rows |
| Shared cache before running more than one web machine | #11. `SimpleCache` is per-machine |
| Use accumulated `recommendation_feedback` to tune ranking | #3. Re-rank quality is currently unmeasured |
| RAG: quote synopsis content directly in the recommendation reason | #3. Reasons are generated from a truncated synopsis |
| Cache recommendations per time window | #9. Repeat queries spend quota on near-identical answers |
| Expand cinema coverage | The per-cinema quota (#7) already anticipates more venues |
| UI polish: richer cards, mobile-first layout | #10. Every component is hand-written twice, so visual changes cost double |
