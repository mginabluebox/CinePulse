# CinePulse documentation

Documentation of the system as built (branch `test`, Aug 2026). These documents are for
**understanding** the system: what it does, why it is shaped this way, and how to extend it.

Instructions for **working** in the repository - workflow, commands, safety constraints, and
conventions - are in [AGENTS.md](../AGENTS.md).

**How this is split.** [decisions.md](decisions.md) is the only doc that evaluates: every tradeoff,
limitation, and known constraint lives there, including the roadmap. Every other doc describes how
the system works and stays neutral, linking to `decisions.md` for the "why" rather than arguing it
in place. Keep it that way when editing: judgment in one file is judgment you can revise in one
place.

## Understanding the system

| Document | Covers |
|----------|--------|
| [overview.md](overview.md) | What the product does, tracked cinemas, configuration, running it locally from zero |
| [architecture.md](architecture.md) | Offline/online split, repository layout, CI, failure modes, observability, testing |
| [decisions.md](decisions.md) | Why the system is shaped this way, what each choice costs, known constraints, and what to change next |
| [data-model.md](data-model.md) | The four tables, their constraints, and where the schema comes from |
| [database_schema.sql](database_schema.sql) | `pg_dump --schema-only` of production. Authoritative; regenerate after any schema change |

## Components

| Document | Covers |
|----------|--------|
| [scraping-pipeline.md](scraping-pipeline.md) | Spiders, DB pipeline, stale sweep, title normalization, embedding and enrichment sync |
| [calendar-view.md](calendar-view.md) | Landing page calendar: queries, `build_calendar()`, week loading, filters |
| [search.md](search.md) | Semantic showtime search: retrieval, per-cinema quota, search UI |
| [recommend.md](recommend.md) | Two-stage recommender, prompt contract, rate limits, swipe UI, feedback |
| [frontend.md](frontend.md) | Template and `script.js` organization, mirrored implementations, design system |

## Changing the system

| Document | Covers |
|----------|--------|
| [AGENTS.md](../AGENTS.md) | Workflow, commands, merge gates, safety constraints, multi-file changes (add a cinema, add a field end-to-end), scraper edge cases, deployment runbook |

## Reading order

New to the project: [overview.md](overview.md) → [architecture.md](architecture.md) →
[decisions.md](decisions.md), then the component doc for whatever you are touching.

About to change something: [AGENTS.md](../AGENTS.md) first, then the component doc for the layer you
are touching.
