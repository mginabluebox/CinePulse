# Calendar view

The landing page (`/`): a week-by-week showtime calendar across all tracked cinemas. Server-rendered
Jinja plus vanilla JS, no build step.

Files: `src/app.py` (route, `build_calendar()`), `src/database/queries.py:get_showtimes()`,
`src/templates/landing.html`, `_week_tabs.html`, `_week_panels.html`, inline JS in `landing.html`.

## Request flow

```
GET /  ⟨cache 300 s⟩
  ├─ _et_date_range(0, 7, from_now=True)  → (start = now in ET, end = today+7)
  ├─ get_showtimes(start, end)            → flat list of showtime rows
  ├─ build_calendar(rows, _date_list(0,7))→ 7 day buckets, films grouped per day
  ├─ get_last_scraped_at()                → "3 Aug 2026" footer stamp
  └─ get_last_showtime_date()             → total_weeks
```

Week 1 starts at the current ET timestamp rather than midnight, so screenings that have already
started are not offered. Later weeks start at midnight of their first day.

`total_weeks = ceil((days_until_last_showtime + 1) / 7)`, floored at 1, so week navigation never
offers a week the database cannot fill.

### `get_showtimes(start_date, end_date)`

One ORM query, `showtimes` LEFT JOIN `movies`, ordered by `show_time` ascending. It returns the
denormalized film fields from the showtime row plus the enrichment fields from the movie row:

- `image_url` is `coalesce(showtimes.image_url, movies.tmdb_poster_url)`.
- `format` is `coalesce(showtimes.format, '-')`.
- `showdate` / `showtime` are formatted in SQL (`YYYY-MM-DD`, `HH12:MI AM`).
- ratings, `tmdb_genres`, `tmdb_original_title`, `scraped_title_normalized`, `tmdb_trailer_url`
  come from `movies`.

Add columns carefully: the query orders and groups by fields the calendar assembly relies on.

### `build_calendar(showtimes, all_dates)`

Turns the flat row list into render-ready day buckets.

- **Grouping key** is `(movie_id or title, cinema)` within a date. The same film at two venues on
  the same day is two entries, which is what the per-cinema layout wants.
- **Backfill**: `image_url`, `synopsis`, and `details_link` are filled from any row in the group, so
  one sparse showtime row does not blank out a card that another row could populate.
- **Period bucketing**: `parse_showtime_mins()` converts `"7:30 PM"` to minutes from midnight
  (unparseable → 9999, sorting last); `showtime_period()` buckets `< 720` morning, `< 1020`
  afternoon, else evening.
- **Ordering**: showtimes within a film sort by minutes; films within a day sort by their earliest
  showtime.
- **Empty days**: passing `all_dates` guarantees exactly 7 entries per week. A date with no rows
  gets `empty: True` and renders "No screenings scheduled" rather than vanishing, which keeps the
  day tabs aligned with the calendar.
- **Labels**: the day abbreviation comes from the scraped `show_day` when present, otherwise from
  the date itself.

## `GET /api/calendar_week/<int:week_num>`

Weeks 2+, loaded on demand. Cached 300 s. `week_num < 2` returns **400** `{"error": "invalid week"}`.

Returns pre-rendered HTML, not JSON data:

```json
{ "tabs": "<button class=\"cp-day-tab\" …>…", "panels": "<div class=\"cp-day-panel\" …>…" }
```

The route renders the same `_week_tabs.html` and `_week_panels.html` templates the server used for
week 1, so markup is identical across weeks and the delegated click handlers and cinema filter work
on injected DOM without special cases.

The client (`landing.html`) tracks `currentWeek`, `totalWeeks`, and a `loadedWeeks` set, appends
fetched tabs before the load button and panels before `#loadMoreWeekRow`, calls
`reapplyCinemaFilter()` on the new DOM, then `goToWeek()`. Already-loaded weeks switch without a
refetch. `goToWeek()` shows only that week's tabs, activates its first day, and hides the prev/next
buttons at the ends of the range.

## Rendering

`_week_panels.html` defines the `render_film_banner(film, psts, extra_class)` macro and the day
panel structure:

```
day panel
└─ period section (Morning / Afternoon / Evening)   - only if it has films
   └─ cinema label + cinema group                   - grouped by film.cinema
      ├─ film banner × 2                            - first two visible
      ├─ "Show N more" button                       - one-way reveal, then removes itself
      └─ film banner × N (cp-hidden-film)
```

A film banner carries: thumbnail, rating chips, genre tags, title with a details arrow, original
title, director / year / runtime meta line, a trailer button, and the showtime chips for that
period.

- **Rating chips** are colour-coded: IMDb `≥ 7` good / `≥ 4` meh; Rotten Tomatoes `≥ 60` fresh
  (fresh and rotten use different icons); Metacritic `≥ 61` good / `≥ 40` meh. Icons are brand
  logos from Wikimedia.
- **Original title** renders only when `tmdb_original_title` differs from the normalized scraped
  title, so English-language films do not show a redundant second title.
- **Format tag** on a showtime chip is suppressed for `DCP`, `DIGITAL`, `UNKNOWN`, and `-`, so only
  meaningful formats (35mm, 70mm, …) surface.
- **Sold out** (`ticket_link == 'sold_out'`) renders as a disabled `<span>` chip instead of a link.

`renderFilmBanner()` in `script.js` is the client-side mirror of this macro, used for search results
and the swipe summary. It is one of four mirrored implementations between the server and the
frontend: see [frontend.md](frontend.md#mirrored-implementations).

## Interactions

All in the inline script at the bottom of `landing.html`, all delegated so week 2+ markup works
without rebinding.

| Interaction | Behaviour |
|-------------|-----------|
| Day tabs | Horizontal drag-to-scroll and wheel-to-scroll; clicking a tab activates the matching panel |
| Banner expand | Clicking a banner with a synopsis expands it, collapsing any other expanded banner; the synopsis fades in after the 380 ms expand transition |
| Show more | Reveals the hidden films in a cinema group and removes the button (one-way) |
| Cinema filter | Multi-select pills; empty selection means "all". Hides non-matching cinema groups and labels, then hides period sections left with no visible group |
| Week nav | Prev switches instantly; next fetches and injects the week if not already loaded |
| Search toggle | Expands the inline search form; submitting swaps the calendar view for the results view (see [search.md](search.md)) |

The cinema filter also applies to search results: `_applyFilterToDOM()` calls back into
`renderShowtimePage(1)` when the search view is visible, and `getFilteredShowtimeResults()` keeps
only movies with a showtime at a selected cinema.
