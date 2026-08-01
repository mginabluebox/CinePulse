# Semantic search

Retrieval-only search over everything currently playing. The user describes what they want in plain
English; results are ranked by cosine similarity between the query embedding and the precomputed
movie embeddings. **No LLM is involved** - only the embedding call.

It lives on the landing page as an inline search that swaps the calendar for a paginated results
view. For the LLM-reranked, 5-pick experience see [recommend.md](recommend.md).

Files: `src/bots/get_recommendation.py:search_showtimes_by_embedding()`, `src/app.py`
(`/api/search_showtimes`), `src/static/script.js` (search form, accordion, pagination),
`src/templates/landing.html` (`#searchResultsView`).

## `POST /api/search_showtimes`

```jsonc
// request
{ "query": "slow-burn noir" }

// 200 - a bare JSON array, ordered best match first
[ {
    "movie_id": 123, "title": "...", "director": "...", "year": 1994,
    "runtime": 110, "synopsis": "...", "image_url": "...",
    "similarity": 0.41,
    "showtimes": [ { "showdate": "2026-08-03", "showtime": "07:30 PM",
                     "show_day": "Monday", "cinema": "METROGRAPH",
                     "ticket_link": "...", "format": "35mm", … } ],
    "imdb_rating": 8.1, "omdb_rt_score": 92, "omdb_metacritic_score": 78,
    "tmdb_genres": ["Drama"], "tmdb_original_title": "...",
    "scraped_title_normalized": "...", "tmdb_trailer_url": "..."
} ]
```

An empty or whitespace-only query returns `[]` without calling OpenAI. `LLMError` / `DBError` /
`ParseError` map to **502**, anything else to **500**. The route is not rate limited and not cached.

Note the shape difference from the recommender: no `reason`, no `cinemas` grouping, and posters come
back as `image_url` rather than `scraped_image_url`.

## Ranking

`search_showtimes_by_embedding(query, engine, top_n_per_cinema=30, showtimes_per_movie=20)`:

1. **Candidates** - `get_movies_with_future_showtimes()`: every movie with at least one showtime at
   or after `now()` **and** a non-null embedding, grouped and ordered by earliest upcoming showtime.
   Unlike the recommender, sold-out showtimes are *not* excluded here.
2. **Embed** the query once via `generate_embedding()` (always OpenAI).
3. **Score** every candidate by cosine similarity in Python, sorted descending, with no global
   cutoff.
4. **Hydrate** up to 20 future showtimes per movie via `get_future_showtimes_for_movie_ids()`.
5. **Apply the per-cinema quota** while walking the ranked list.

### The per-cinema quota

A movie qualifies if **any** cinema it plays at still has quota remaining (default 30 per cinema).
When it is selected, quota is consumed for each of its cinemas that is still below the limit.
Movies with no future showtimes left are skipped.

The effect is that every venue contributes results before any one venue's tail does. The list is
therefore **not** a pure global ranking: relative order still follows similarity, but a film whose
cinemas have all exhausted their quota is dropped entirely rather than demoted to the end.

Why the quota exists and what it costs:
[decisions.md](decisions.md#7-search-applies-a-per-cinema-quota-instead-of-a-global-ranking).

## Search UI

Entry point is the toggle button next to the calendar header; it expands the inline form
(`#showtimeSearchForm`) and focuses the input.

On submit:

1. Empty query → the placeholder is replaced with an inline error message and the input turns red.
   No request is sent.
2. The button collapses to a spinner while the request is in flight.
3. On success, results are stored client-side, page 1 renders, and `#calendarView` is hidden in
   favour of `#searchResultsView`.
4. On a non-2xx response the server's `error` message is shown in the input placeholder; a thrown
   fetch shows "Network error. Try again."

Results render as an accordion of film banners via `renderShowtimeAccordion()`:

- **10 per page**, with Prev / Next, a "Showing X-Y of N" label, and a jump-to-page input that
  clamps to the valid range. Pagination hides itself when everything fits on one page.
- Each banner shows a **`NN% match`** chip (`Math.round(similarity * 100)`).
- Showtimes are grouped by cinema (`renderShowtimeByCinema`), then by date within a cinema, with an
  arrow next to the cinema name linking to that film's page on the venue's site. Beyond **2 dates
  per cinema** the remaining dates collapse into the expandable region.
- A banner is expandable if it has a synopsis or overflow dates; expanding collapses any other
  expanded banner, and the synopsis fades in after the 380 ms transition.
- The **cinema filter pills apply to search results too**: `getFilteredShowtimeResults()` keeps only
  movies with a showtime at a selected cinema, and changing the filter re-renders from page 1.
- **Back** restores the calendar view, clears the query, and closes the search form.

Rendering goes through the same `renderFilmBanner()` helper as the swipe summary, itself the mirror
of the `render_film_banner` Jinja macro used by the calendar. See
[calendar-view.md](calendar-view.md#rendering) for the shared banner contract and
[frontend.md](frontend.md#mirrored-implementations) for the full list of paired implementations.
