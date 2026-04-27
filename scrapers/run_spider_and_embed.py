"""Run all cinema spiders, embed new/changed movies, then enrich with OMDb/TMDb.

Usage (from repo root):
    python scrapers/run_spider_and_embed.py                    # full pipeline, writes to DB
    python scrapers/run_spider_and_embed.py --dry-run          # scrape 10 movies/cinema, no DB writes
    python scrapers/run_spider_and_embed.py --refresh-enrichment  # force re-enrich all movies
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "scrapers.settings")

from src.database.sync_embeddings import sync_embeddings, DEFAULT_BATCH_SIZE  # noqa: E402
from src.database.sync_enrichment import sync_enrichment  # noqa: E402

LOGGER = logging.getLogger("run_spider_and_embed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DRY_RUN_OUTPUT_DIR = ROOT / "tests" / "scraper"
DRY_RUN_MOVIES_PER_CINEMA = 10


def run_spider() -> None:
    process = CrawlerProcess(get_project_settings())
    process.crawl('metrograph')
    process.crawl('film_forum')
    process.crawl('ifc_center')
    process.start()


def _run_dry_spiders(n_movies: int = DRY_RUN_MOVIES_PER_CINEMA) -> Path:
    """Scrape up to n_movies per cinema without writing to the DB.

    Returns the path of the JSON file written to tests/scraper/.
    """
    from scrapers.pipelines import DryRunCollectorPipeline

    DryRunCollectorPipeline.reset(n_movies)

    settings = get_project_settings()
    settings.set('ITEM_PIPELINES', {'scrapers.pipelines.DryRunCollectorPipeline': 300})

    process = CrawlerProcess(settings)
    process.crawl('metrograph')
    process.crawl('film_forum')
    process.crawl('ifc_center')
    process.start()

    # Group raw showtime items into movie records for readability
    movies_by_cinema: dict[str, dict[str, dict]] = defaultdict(dict)
    for item in DryRunCollectorPipeline.items:
        cinema = item.get('cinema', 'UNKNOWN')
        title = item.get('title', '')
        if title not in movies_by_cinema[cinema]:
            synopsis = item.get('synopsis') or ''
            movies_by_cinema[cinema][title] = {
                'title': title,
                'pipeline_clean_title': item.get('_pipeline_clean_title'),
                'pipeline_dedup_key': item.get('_pipeline_dedup_key'),
                'pipeline_api_lookup': item.get('_pipeline_api_lookup'),
                'year': item.get('year'),
                'director1': item.get('director1'),
                'director2': item.get('director2'),
                'runtime': item.get('runtime'),
                'format': item.get('format'),
                'synopsis': synopsis[:300] + ('…' if len(synopsis) > 300 else ''),
                'image_url': item.get('image_url'),
                'details_link': item.get('details_link'),
                'showtimes': [],
            }
        show_time = item.get('show_time')
        if show_time:
            movies_by_cinema[cinema][title]['showtimes'].append(str(show_time))

    output: dict = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'n_movies_per_cinema': n_movies,
    }
    for cinema in sorted(movies_by_cinema):
        output[cinema] = list(movies_by_cinema[cinema].values())

    DRY_RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out_path = DRY_RUN_OUTPUT_DIR / f'dry_run_{ts}.json'
    out_path.write_text(json.dumps(output, indent=2, default=str, ensure_ascii=False))
    LOGGER.info('Dry-run complete. Results written to %s', out_path)
    return out_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run cinema spiders then embed new/updated movies")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of movies to embed")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Embedding batch size")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between embedding batches")
    parser.add_argument("--refresh-all", action="store_true", help="Force re-embed all movies, ignoring hashes")
    parser.add_argument("--refresh-enrichment", action="store_true",
                        help="Force re-enrich all movies with future showtimes, ignoring enriched_at")
    parser.add_argument("--dry-run", action="store_true",
                        help=f"Scrape {DRY_RUN_MOVIES_PER_CINEMA} movies per cinema, no DB writes; save to tests/scraper/")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.dry_run:
        _run_dry_spiders()
        return

    LOGGER.info("Running all cinema spiders...")
    run_spider()
    LOGGER.info("Spider complete. Starting embedding sync...")
    sync_embeddings(
        refresh_all=args.refresh_all,
        limit=args.limit,
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        dry_run=False,
    )
    LOGGER.info("Embeddings done. Starting enrichment sync...")
    sync_enrichment(
        apply=True,
        refresh_all=args.refresh_enrichment,
        limit=args.limit,
        sleep_s=args.sleep,
    )
    LOGGER.info("Pipeline finished")


if __name__ == "__main__":
    main()
