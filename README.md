# CinePulse

Aggregates New York repertory and independent cinema schedules into one calendar, and lets you find
something to watch by describing it in plain English.

**Live demo:** https://cinepulse.fly.dev/  
<p align="center">
  <img src="docs/demos/CinePulse_Demo_20260301.gif" width="500" />
</p>

## Documentation
Full docs live in [docs/](docs/README.md):
[overview](docs/overview.md) ·
[architecture](docs/architecture.md) ·
[decisions](docs/decisions.md) ·
[data model](docs/data-model.md) ·
[scraping pipeline](docs/scraping-pipeline.md) ·
[calendar view](docs/calendar-view.md) ·
[search](docs/search.md) ·
[recommendations](docs/recommend.md) ·
[frontend](docs/frontend.md)

Working in the repo (workflow, commands, safety constraints): [AGENTS.md](AGENTS.md).

## Architecture

```
                       cinema sites  +  JSON APIs
                                  │
   ┌─ OFFLINE ─ weekly cron ──────▼───────────────────────────────┐
   │                                                              │
   │   Scrapy spiders  ──►  OpenAI embeddings  ──►  OMDb + TMDb   │
   │                                                ratings,      │
   │                                                posters       │
   └──────────────────────────────┬───────────────────────────────┘
                                  │ writes
                   ┌──────────────▼───────────────┐
                   │   PostgreSQL  +  pgvector    │
                   │   movies · showtimes         │
                   └──────────────┬───────────────┘
                                  │ reads
   ┌─ ONLINE ─ Flask on gunicorn ─▼───────────────────────────────┐
   │                                                              │
   │   calendar        search              recommend              │
   │   Jinja           cosine ranking      cosine → LLM re-rank   │
   │                                       to 5 picks + reasons   │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
                  Browser - server-rendered Jinja + vanilla JS
```

Full detail in [architecture.md](docs/architecture.md).

## Quickstart
Requirements: Python 3.10+, PostgreSQL 14+ with pgvector, and an OpenAI API key - required for
embeddings even when running Ollama for chat.

```bash
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
export FLASK_APP=src/app.py && flask run
```

## What's next
Planned work is tracked in
[decisions.md](docs/decisions.md#what-we-would-change-next), where each item is stated as the cost
of the design decision that produced it.
