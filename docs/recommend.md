# Recommendations

The `/app` page: the user describes a mood or taste in plain English and gets **5 films** that are
actually playing in the next 7 days, each with a one-line reason, presented as a swipe deck.

This is the only feature that calls a chat LLM at request time. The cheaper, retrieval-only sibling
is [search.md](search.md).

Files: `src/bots/get_recommendation.py`, `src/bots/llm_selector.py`, `src/app.py`
(`/api/recommend_movies`, `/api/feedback`), `src/templates/index.html`, `src/static/script.js`.

## Two stages

`recommend_movies_by_embedding(preference, engine, candidate_pool=30, top_k=5,
showtimes_per_movie=5, run_id=…, session_token=…, start_date=…, end_date=…)`:

| # | Step | Detail |
|---|------|--------|
| 1 | Candidates | `get_movies_with_future_showtimes(exclude_sold_out=True, end_date=…)` - movies with a future, non-sold-out showtime **and** a non-null embedding |
| 2 | Embed | `generate_embedding(preference)`, one OpenAI call |
| 3 | Score | `_score_candidates_by_similarity()` - cosine similarity in Python, keep the top **30** |
| 4 | Re-rank | one `call_llm()` (`max_tokens=512`, `temperature=0`) asking for exactly 5 picks |
| 5 | Parse | `_parse_movie_reason_map()` validates the JSON strictly |
| 6 | Hydrate | up to 5 upcoming non-sold-out showtimes per pick, grouped by cinema |

Because embeddings are precomputed offline, request latency is one embed call plus one LLM call.
Why the re-rank exists at all, and why search does without it, is in
[decisions.md](decisions.md#3-recommendation-re-ranks-with-an-llm-search-does-not).

Each stage returns early on empty input: no candidates, no embedding, or no scored candidates all
produce `[]` rather than an error.

### Timezone note

Step 1 deliberately passes `start_date=None` so the lower cutoff is Postgres `func.now()`. Passing
the app's ET-formatted string would be interpreted as UTC, a 4-hour offset that lets already-started
screenings through as candidates. Step 6 uses the same `func.now()` cutoff, so the two stages agree
on what "future" means. `end_date` is still passed, bounding recommendations to the 7-day window the
calendar shows.

### Prompt

`build_movie_prompt(preference, candidates)` renders each candidate as:

```
MovieID: 123  Title: …
   Director: …
   Synopsis: …          (truncated to 300 chars on a word boundary)
```

and instructs the model to: select exactly 5, use only the supplied MovieIDs, prefer strong matches
and fill with next-best if fewer than 5 match, return exactly one JSON object
`{"MovieID": "Reason", …}` with no surrounding text, keep each reason to 1-2 sentences and at most
30 words, and address the user directly ("you" / "your").

### Parsing

`_parse_movie_reason_map()` runs `json.loads` on the response, and on failure retries against the
first `{...}` block found by regex. Keys are coerced to `int`; non-numeric keys are dropped. It
raises `ParseError` if no object parses, or if nothing numeric survives.

The LLM's key order is preserved as the display order, capped at `top_k = 5`. IDs the model
invented (not in the candidate lookup) are discarded.

**The prompt and the parser are coupled.** Changing the output format requires updating
`_parse_movie_reason_map()` and `tests/test_recommendation_units.py` together.

### Hydration

`get_future_showtimes_for_movie_ids(selected_ids, limit_per_movie=5, exclude_sold_out=True)`,
grouped by cinema for the response. The poster resolves in order `scraped_image_url` → the first
showtime `image_url` → `tmdb_poster_url`.

A selection whose showtimes have all passed between stage 1 and stage 6 is dropped with a logged
warning, so a response can legitimately contain fewer than 5 films.

## `POST /api/recommend_movies`

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

`id` duplicates `movie_id` for the frontend's swipe handling. `run_id` is a fresh UUID per request
and ties the `recommendation_logs` row to the `recommendation_feedback` rows that follow.

## Rate limiting

Applied **only** when `LLM_PROVIDER == 'openai'`, before any work is done. `check_rate_limits()`
counts successful calls (`error_code = 0`) in `recommendation_logs` since
`date_trunc('day', now())`:

- `DAILY_GLOBAL_LIMIT = 35` - all users combined → "Recommendations are at capacity for today."
- `SESSION_LIMIT = 5` - per `session_token` → "You've used your 5 recommendations for today."

Counting only successes means a failed LLM call does not burn the user's quota.

The session token is a `crypto.randomUUID()` persisted in `localStorage` under
`cinepulse_session_token`. It identifies a browser, not a person, and is trivially resettable. It is
a cost guardrail, not a security control - the endpoint is public and unauthenticated, and these two
numbers are the only thing bounding its cost. See
[decisions.md](decisions.md#9-rate-limiting-is-per-browser-and-cost-shaped).

## Swipe UI

`/app` renders `index.html`; all behaviour is in `script.js`.

**Submitting.** Empty preference shows an inline error without a request. The button collapses to a
spinner while in flight. A non-2xx response surfaces the server's `error` message verbatim, which is
how rate-limit messages reach the user.

**The deck.** `renderMovieCards()` builds one `.swipe-card` per result, rendered in reverse so the
top pick sits on top, with `z-index` stacking. Each card carries poster, title, original title (only
when it differs from the normalized scraped title), year / runtime / director, trailer link, the
"Why you might like it" reason, and the synopsis. The full result object is stashed in
`dataset.payload`.

**Swiping.** Pointer events with a **120 px** threshold. Rotation is proportional to drag
(`x / 20` degrees); crossing the threshold shows the like or nope overlay. On release past the
threshold the card animates off-screen over 300 ms and is removed; short of it, it springs back.
Drags starting on an anchor are ignored so the trailer link stays clickable.

**Feedback.** Each committed swipe POSTs to `/api/feedback` with `decision_ms` measured from
pointerdown. `.catch(() => {})` swallows failures so the interaction never blocks.

**Summary.** When the deck empties, `renderMovieSwipeSummary()` replaces it with "Our Picks": every
swiped film as a film banner with a like/dislike badge, sorted liked first, then by similarity
descending, then by earliest showtime. Showtimes are grouped by cinema; reason and synopsis sit in
the expandable region. It reuses `renderFilmBanner()`, the same component as search results - see
[calendar-view.md](calendar-view.md#rendering).

## `POST /api/feedback`

```jsonc
{ "movie_id": 123, "liked": true,
  "run_id": "<uuid>", "session_token": "<uuid>",
  "decision_ms": 2400, "similarity": 0.42, "title": "...", "year": 1994 }
```

`movie_id` and `liked` are required; everything else is optional. Missing required fields → **400**.
Success → `{"status": "ok"}`. Rows land in `recommendation_feedback` (see
[data-model.md](data-model.md#recommendation_feedback)), which is the raw material for evaluating
and tuning ranking later.
