# CinePulse
Dashboard for sourcing and recommending what's playing at local cinemas.

## Embedding sync
- Requires the `pgvector` extension in Postgres and the `movies.embedding` column defined as `vector(1536)`.
- Set `OPENAI_API_KEY` (and optionally `OPENAI_EMBED_MODEL`) in your `.env` file.
- Generate embeddings after each scraper run:

```bash
python src/database/sync_embeddings.py --dry-run   # preview work
python src/database/sync_embeddings.py             # writes embeddings
```

- Use `--refresh-all` to recompute existing vectors or `--limit`/`--batch-size` to control throughput.
