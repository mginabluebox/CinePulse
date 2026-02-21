"""Run the Metrograph spider and then embed any new or changed movies.

Usage (from repo root):
    python -m scrapers.run_spider_and_embed

The embedding step reuses sync_embeddings.py logic, so it only writes rows whose
hash/model changed unless --refresh-all is provided.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings


# Ensure project root is on path so we can import src.*
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure Scrapy picks up the local settings when run as a module
os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "scrapers.settings")

# from scrapers.run_spider import run_spider  # noqa: E402
from src.database.sync_embeddings import sync_embeddings, DEFAULT_BATCH_SIZE  # noqa: E402

LOGGER = logging.getLogger("run_spider_and_embed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

def run_spider():
    """
    Run the Metrograph spider and process the scraped data.
    """
    process = CrawlerProcess(get_project_settings())
    process.crawl('metrograph')
    process.start()

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run spider then generate embeddings for new/updated movies")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of movies to embed after scraping")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Embedding batch size")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between embedding batches")
    parser.add_argument("--refresh-all", action="store_true", help="Force re-embed all movies, ignoring hashes")
    parser.add_argument("--dry-run", action="store_true", help="Scrape then show which movies would embed without writing")
    return parser

def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    LOGGER.info("Running Metrograph spider...")
    run_spider()
    LOGGER.info("Spider complete. Starting embedding sync...")

    sync_embeddings(
        refresh_all=args.refresh_all,
        limit=args.limit,
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        dry_run=args.dry_run,
    )
    LOGGER.info("Scrape + embed pipeline finished")


if __name__ == "__main__":
    main()
