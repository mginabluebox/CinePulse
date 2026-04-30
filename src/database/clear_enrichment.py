"""Clear TMDB/OMDB enrichment columns for a specific movie ID.

Useful for manually fixing false-positive enrichment matches. After clearing,
the movie's enriched_at is set to NULL so sync_enrichment.py picks it up on
the next run.

Usage (from repo root):
    python src/database/clear_enrichment.py --movie-id 695          # dry-run
    python src/database/clear_enrichment.py --movie-id 695 --apply  # execute
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from src.database.models import Movie
from src.database.setup_db import get_engine, get_session

LOGGER = logging.getLogger('clear_enrichment')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

OMDB_COLS = [
    'imdb_id',
    'imdb_rating',
    'imdb_votes',
    'omdb_rt_score',
    'omdb_metacritic_score',
]

TMDB_COLS = [
    'tmdb_id',
    'tmdb_original_title',
    'tmdb_genres',
    'tmdb_origin_countries',
    'tmdb_original_language',
    'tmdb_spoken_languages',
    'tmdb_tagline',
    'tmdb_overview',
    'tmdb_runtime',
    'tmdb_collection_name',
    'tmdb_poster_url',
    'tmdb_release_date',
    'tmdb_trailer_url',
    'tmdb_title_zh',
]

ALL_ENRICHMENT_COLS = OMDB_COLS + TMDB_COLS + ['enriched_at']


def _fmt(val) -> str:
    if val is None:
        return 'NULL'
    if isinstance(val, list):
        return str(val)
    s = str(val)
    return s[:80] + '…' if len(s) > 80 else s


def clear_enrichment(movie_id: int, apply: bool) -> None:
    engine = get_engine()
    session = get_session(engine)
    try:
        movie = session.get(Movie, movie_id)
        if movie is None:
            LOGGER.error('Movie ID %d not found.', movie_id)
            sys.exit(1)

        LOGGER.info('Movie [%d] %r  (year=%s, cinema=%s)', movie.id, movie.title, movie.year, movie.scraped_cinema)
        LOGGER.info('')
        LOGGER.info('Current enrichment values:')

        has_any = False
        for col in ALL_ENRICHMENT_COLS:
            val = getattr(movie, col, None)
            if val is not None:
                has_any = True
            LOGGER.info('  %-30s %s', col, _fmt(val))

        if not has_any:
            LOGGER.info('')
            LOGGER.info('No enrichment data found — nothing to clear.')
            return

        LOGGER.info('')
        if not apply:
            LOGGER.info('DRY-RUN — no writes. Pass --apply to clear these values.')
            return

        for col in ALL_ENRICHMENT_COLS:
            setattr(movie, col, None)
        session.commit()

        LOGGER.info('Cleared all enrichment columns for movie ID %d.', movie_id)
        LOGGER.info('enriched_at is now NULL — movie will be re-queued on next sync_enrichment.py run.')
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Clear TMDB/OMDB enrichment for a movie ID.')
    parser.add_argument('--movie-id', type=int, required=True, help='Movie ID to clear')
    parser.add_argument('--apply', action='store_true', help='Execute the clear (default: dry-run)')
    args = parser.parse_args()
    clear_enrichment(args.movie_id, apply=args.apply)


if __name__ == '__main__':
    main()
