# Frontend

Server-rendered Jinja plus one vanilla JavaScript file. No framework, no build step, no bundler.
The rationale and its cost are in [decisions.md](decisions.md#10-the-frontend-is-server-rendered-jinja-plus-vanilla-js).

## Files

| File | Role |
|------|------|
| `src/templates/landing.html` | `/` - calendar page, cinema filter, inline search, week navigation. Carries its own inline `<script>` for calendar-only behaviour |
| `src/templates/_week_tabs.html` | Day tab buttons for one week. Rendered inline for week 1, returned as a fragment for weeks 2+ |
| `src/templates/_week_panels.html` | Day panels for one week, plus the `render_film_banner()` macro |
| `src/templates/index.html` | `/app` - recommendation page. Markup only; all behaviour is in `script.js` |
| `src/static/script.js` | Loaded by **both** pages. Guards on element presence, so each page runs only the half that applies to it |
| `src/static/style.css` | All styling, including the `:root` design tokens |

Two pages share one script. Every block in `script.js` starts with a null check on the element it
drives (`if (movieForm) { … }`, `if (showtimeSearchForm) { … }`), which is what keeps the landing
page from executing swipe-deck code and vice versa. Preserve that pattern when adding behaviour.

## `script.js` structure

Everything runs inside one `DOMContentLoaded` handler.

| Region | Functions | Used by |
|--------|-----------|---------|
| Escaping | `esc()`, `escAttr()` | everything that interpolates |
| Title normalization | `normalizeTitle()` | banner and card rendering |
| Showtime formatting | `_fmtTag()`, `_stMins()`, `_stPeriod()`, `renderShowtimeBtns()`, `renderShowtimeByCinema()`, `renderPeriodTimes()` | search results, swipe summary |
| Ratings | `imdbColorClass()`, `rtColorClass()`, `mcColorClass()`, `ratingChip()`, `buildRatingsRow()` | banner rendering |
| Shared component | `renderFilmBanner()` | search results, swipe summary |
| Search | `renderShowtimeAccordion()`, `renderShowtimePage()`, `updateShowtimePagination()`, `getFilteredShowtimeResults()` | `/` |
| Recommend | `renderMovieCards()`, `attachMovieDragHandlers()`, `renderMovieSwipeSummary()`, `logFeedback()`, `ensureSessionToken()` | `/app` |

Calendar-only interactions (day tabs, drag-to-scroll, banner expand, show-more, cinema filter, week
navigation) live in the inline `<script>` at the bottom of `landing.html` instead, because they
operate on server-rendered DOM and need the Jinja-injected `total_weeks` value. `_applyFilterToDOM()`
reaches into `script.js` via `window.renderShowtimePage`, and `script.js` reaches back via the
global `selectedCinemas`. That coupling is the one place the two halves are not independent.

## Mirrored implementations

Because the same components are rendered server-side for the calendar and client-side for search and
the swipe summary, several pieces of logic exist twice. **Editing one without the other produces
markup that silently diverges between pages.**

| JavaScript (`script.js`) | Server-side counterpart | Must agree on |
|--------------------------|-------------------------|---------------|
| `renderFilmBanner()` | `render_film_banner()` macro in `_week_panels.html` | Banner DOM structure, class names, rating chip thresholds, original-title suppression, trailer button |
| `normalizeTitle()` | `_strip_display_suffix()` in `title_normalization.py` | Which display suffixes are stripped before comparing titles |
| `_stMins()`, `_stPeriod()` | `parse_showtime_mins()`, `showtime_period()` in `app.py` | The 720 / 1020 minute period boundaries and the 9999 fallback |
| `_fmtTag()` | The `_show_fmt` check in `_week_panels.html` | The suppressed format list: `DCP`, `DIGITAL`, `UNKNOWN`, `-` |

The rating thresholds appear in three places: `_week_panels.html` (Jinja), `script.js` (the
`*ColorClass` helpers), and nowhere else. IMDb `>= 7` good / `>= 4` meh, Rotten Tomatoes `>= 60`
fresh, Metacritic `>= 61` good / `>= 40` meh.

## Design system

Editorial, indie-cinema aesthetic: warm, typographically controlled, intentionally understated. The
point is that the films are the content and the interface should not compete with them, which is why
the accent colour is rationed and the type does the work of establishing hierarchy.

**Palette.** Defined once in `:root` in `style.css`:

| Token | Value | Role |
|-------|-------|------|
| `--cp-bg` | `#f7f3ec` | Page background, warm off-white |
| `--cp-surface` | `#ffffff` | Cards and raised surfaces |
| `--cp-border` | `#ddd5c5` | Dividers, chip outlines |
| `--cp-text` | `#1a1510` | Primary text, section titles |
| `--cp-text-muted` | `#7a7068` | Meta lines, sub-labels such as cinema names |
| `--cp-accent` | `#c42b2b` | Primary actions, hover, active indicators |
| `--cp-accent-hover` | `#9e1f1f` | Accent hover state |
| `--cp-navy` | `#1e2157` | Secondary emphasis |
| `--cp-rating-good` / `-meh` / `-bad` | `#3a7a35` / `#8a6d1e` / `#c42b2b` | Rating chip states |

**Typography.** Space Grotesk (Google Fonts, loaded non-blocking with a `media="print"` swap and a
`<noscript>` fallback) for headings, labels, and navigation. System UI stack for body and meta text.
Labels and section titles are uppercase with letter-spacing.

**Hierarchy.** Section titles use `--cp-text` with a border-bottom, reading as editorial dividers.
Sub-labels such as cinema names within a period use `--cp-text-muted` at a lighter weight and
smaller size so they clearly read as secondary.

**Accent discipline.** Red is reserved for primary actions, hover states, and active indicators. It
is never decoration. This is the rule most easily broken by well-meaning additions.

**Spacing.** Generous whitespace between sections; tight, scannable component interiors.

**Component vocabulary.** New components follow existing patterns rather than inventing a visual
language: pill buttons match `.cp-cinema-filter-btn`, text toggles match `.cp-show-more-btn`, inline
links match `.cp-details-arrow`.

The enforceable form of these rules is in [AGENTS.md](../AGENTS.md) under repository conventions.

## Security notes

All user-controlled and API-returned values pass through `esc()` (HTML entities) or `escAttr()`
(`encodeURI`) before interpolation into template strings. `renderFilmBanner()` and the card renderer
build HTML by string concatenation, so an unescaped interpolation is an XSS vector. Synopsis, title,
reason, and cinema fields all originate from scraped third-party HTML and must be treated as
untrusted.
