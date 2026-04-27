"""Enrich movie records with OMDb/TMDb metadata.

Usage (from repo root):
    python src/database/sync_enrichment.py                        # dry-run: preview enrichment candidates
    python src/database/sync_enrichment.py --apply                # enrich and write to DB
    python src/database/sync_enrichment.py --refresh-all          # dry-run: re-enrich all movies
    python src/database/sync_enrichment.py --refresh-all --apply  # write re-enriched values for all
    python src/database/sync_enrichment.py --limit 10             # cap records processed
    python src/database/sync_enrichment.py --sleep 0.5            # seconds between API calls
    python src/database/sync_enrichment.py --refresh-count 50     # backfill 50 unenriched movies (full DB, no future-showtime filter)
    python src/database/sync_enrichment.py --refresh-count 50 --apply
    python src/database/sync_enrichment.py --backfill-titles      # only backfill scraped_title_normalized
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from sqlalchemy import or_, select, exists

from src.database.dedup_movies import _api_lookup_title
from src.database.models import Movie, Showtime
from src.database.setup_db import get_engine, get_session

LOGGER = logging.getLogger('sync_enrichment')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

OMDB_KEY = os.getenv('OMDB_API_KEY')
TMDB_KEY = os.getenv('TMDB_API_KEY')
TMDB_IMG_BASE = 'https://image.tmdb.org/t/p/w500'

_EDITION_SUFFIX_RE = re.compile(
    r"\s*:?\s*(?:the\s+)?(?:director['’‘]s|final|extended|unrated|theatrical)\s+cut\s*$",
    flags=re.IGNORECASE,
)


def _validate_env() -> None:
    missing = [k for k in ('OMDB_API_KEY', 'TMDB_API_KEY') if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


def _strip_edition_suffix(title: str) -> str:
    return _EDITION_SUFFIX_RE.sub('', title).strip()


# ── OMDb ──────────────────────────────────────────────────────────────────────

def _call_omdb(title: str, year: str | None) -> dict | None:
    params = {'t': title, 'apikey': OMDB_KEY}
    if year:
        params['y'] = year
    r = requests.get('http://www.omdbapi.com/', params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    return None if data.get('Response') == 'False' else data


def _parse_omdb(data: dict) -> dict:
    imdb_rating = None
    try:
        v = data.get('imdbRating')
        if v and v != 'N/A':
            imdb_rating = float(v)
    except (ValueError, TypeError):
        pass

    imdb_votes = None
    try:
        v = (data.get('imdbVotes') or '').replace(',', '')
        if v and v != 'N/A':
            imdb_votes = int(v)
    except (ValueError, TypeError):
        pass

    omdb_rt_score = None
    for rating in (data.get('Ratings') or []):
        if rating.get('Source') == 'Rotten Tomatoes':
            try:
                omdb_rt_score = int(rating['Value'].rstrip('%'))
            except (ValueError, TypeError):
                pass
            break

    omdb_metacritic_score = None
    try:
        v = data.get('Metascore')
        if v and v != 'N/A':
            omdb_metacritic_score = int(v)
    except (ValueError, TypeError):
        pass

    return {
        'imdb_id': data.get('imdbID') or None,
        'imdb_rating': imdb_rating,
        'imdb_votes': imdb_votes,
        'omdb_rt_score': omdb_rt_score,
        'omdb_metacritic_score': omdb_metacritic_score,
    }


# ── TMDb ──────────────────────────────────────────────────────────────────────

def _call_tmdb_find(imdb_id: str) -> int | None:
    r = requests.get(
        f'https://api.themoviedb.org/3/find/{imdb_id}',
        params={'external_source': 'imdb_id', 'api_key': TMDB_KEY},
        timeout=10,
    )
    r.raise_for_status()
    results = r.json().get('movie_results', [])
    return results[0]['id'] if results else None


def _call_tmdb_search(title: str, year: str) -> int | None:
    r = requests.get(
        'https://api.themoviedb.org/3/search/movie',
        params={'query': title, 'year': year, 'api_key': TMDB_KEY},
        timeout=10,
    )
    r.raise_for_status()
    results = r.json().get('results', [])
    return results[0]['id'] if results else None


def _call_tmdb_details(tmdb_id: int) -> dict:
    r = requests.get(
        f'https://api.themoviedb.org/3/movie/{tmdb_id}',
        params={'append_to_response': 'videos,translations', 'api_key': TMDB_KEY},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _parse_tmdb(data: dict) -> dict:
    poster_path = data.get('poster_path')

    release_date = None
    try:
        raw = data.get('release_date')
        if raw:
            release_date = date.fromisoformat(raw)
    except (ValueError, TypeError):
        pass

    # Trailer: YouTube, type Trailer, prefer official
    trailer_url = None
    trailers = [
        v for v in ((data.get('videos') or {}).get('results') or [])
        if v.get('site') == 'YouTube' and v.get('type') == 'Trailer'
    ]
    if trailers:
        official = [v for v in trailers if v.get('official')]
        pick = (official or trailers)[0]
        trailer_url = f"https://www.youtube.com/watch?v={pick['key']}"

    # Chinese title: prefer CN > TW > HK
    tmdb_title_zh = None
    zh = [t for t in ((data.get('translations') or {}).get('translations') or [])
          if t.get('iso_639_1') == 'zh']
    if zh:
        order = {'CN': 0, 'TW': 1, 'HK': 2}
        zh.sort(key=lambda t: order.get(t.get('iso_3166_1', ''), 99))
        title_zh = zh[0].get('data', {}).get('title', '')
        if title_zh:
            tmdb_title_zh = title_zh

    collection = data.get('belongs_to_collection')

    return {
        'tmdb_original_title': data.get('original_title') or None,
        'tmdb_genres': [g['name'] for g in (data.get('genres') or [])],
        'tmdb_origin_countries': data.get('origin_country') or [],
        'tmdb_original_language': data.get('original_language') or None,
        'tmdb_spoken_languages': [l['iso_639_1'] for l in (data.get('spoken_languages') or [])],
        'tmdb_tagline': data.get('tagline') or None,
        'tmdb_overview': data.get('overview') or None,
        'tmdb_runtime': data.get('runtime') or None,
        'tmdb_collection_name': collection['name'] if collection else None,
        'tmdb_poster_url': f'{TMDB_IMG_BASE}{poster_path}' if poster_path else None,
        'tmdb_release_date': release_date,
        'tmdb_trailer_url': trailer_url,
        'tmdb_title_zh': tmdb_title_zh,
    }


# ── Enrichment sync ───────────────────────────────────────────────────────────

def _fetch_backfill_enrichment_movies(session, count: int) -> list[Movie]:
    stmt = (
        select(Movie)
        .where(Movie.enriched_at.is_(None))
        .order_by(Movie.id)
        .limit(count)
    )
    return list(session.scalars(stmt).all())


def _fetch_enrichment_movies(session, refresh_all: bool, limit: int | None) -> list[Movie]:
    now = datetime.now(timezone.utc)
    has_future_showtime = exists().where(
        Showtime.movie_id == Movie.id,
        Showtime.show_time > now,
    )
    stmt = (
        select(Movie)
        .where(has_future_showtime)
        .order_by(Movie.enriched_at.asc().nulls_first(), Movie.id)
    )
    if not refresh_all:
        cutoff = (now - timedelta(days=30)).date()
        stmt = stmt.where(
            or_(
                Movie.enriched_at.is_(None),
                Movie.tmdb_release_date.is_(None),
                Movie.tmdb_release_date >= cutoff,
            )
        )
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def sync_enrichment(
    apply: bool = False,
    refresh_all: bool = False,
    limit: int | None = None,
    sleep_s: float = 0.1,
    backfill_count: int | None = None,
) -> None:
    """Call OMDb + TMDb for each unenriched movie and write results to DB."""
    _validate_env()

    engine = get_engine()
    session = get_session(engine)
    try:
        if backfill_count is not None:
            movies = _fetch_backfill_enrichment_movies(session, backfill_count)
        else:
            movies = _fetch_enrichment_movies(session, refresh_all=refresh_all, limit=limit)
    finally:
        session.close()

    if not movies:
        LOGGER.info('No movies to enrich')
        return

    LOGGER.info('Enriching %d movie(s)', len(movies))
    if not apply:
        LOGGER.info('DRY-RUN — no writes will occur')

    enriched = both_miss = errors = 0
    for movie in movies:
        lookup = movie.scraped_title_normalized or movie.title or ''
        year = str(movie.year) if movie.year else None
        stripped = _strip_edition_suffix(lookup)
        has_edition = stripped != lookup

        LOGGER.info('[%4d] %r  year=%s', movie.id, movie.title, year)

        # ── OMDb ─────────────────────────────────────────────────────────────
        omdb_data = None
        try:
            omdb_data = _call_omdb(lookup, year)
            if omdb_data is None and has_edition and year:
                omdb_data = _call_omdb(lookup, None)        # retry 1: keep title, drop year
            if omdb_data is None and has_edition:
                omdb_data = _call_omdb(stripped, year)      # retry 2: strip suffix, keep year
        except Exception as e:
            LOGGER.warning('  OMDb error: %s', e)
        time.sleep(sleep_s)

        omdb_fields = _parse_omdb(omdb_data) if omdb_data else {}
        imdb_id = omdb_fields.get('imdb_id')
        if omdb_data:
            LOGGER.info('  OMDb HIT  imdb=%s  rating=%s  RT=%s  MC=%s',
                        imdb_id, omdb_fields.get('imdb_rating'),
                        omdb_fields.get('omdb_rt_score'), omdb_fields.get('omdb_metacritic_score'))
        else:
            LOGGER.info('  OMDb MISS')

        # ── TMDb ─────────────────────────────────────────────────────────────
        tmdb_id = None
        try:
            if imdb_id:
                tmdb_id = _call_tmdb_find(imdb_id)
            if not tmdb_id:
                tmdb_id = _call_tmdb_search(lookup, year or '')
            if not tmdb_id and has_edition:
                tmdb_id = _call_tmdb_search(stripped, year or '')
        except Exception as e:
            LOGGER.warning('  TMDb search error: %s', e)
        time.sleep(sleep_s)

        tmdb_fields: dict = {}
        if tmdb_id:
            try:
                details = _call_tmdb_details(tmdb_id)
                tmdb_fields = _parse_tmdb(details)
                tmdb_fields['tmdb_id'] = tmdb_id
                LOGGER.info('  TMDb HIT  id=%d  genres=%s  poster=%s',
                            tmdb_id, tmdb_fields.get('tmdb_genres'),
                            bool(tmdb_fields.get('tmdb_poster_url')))
            except Exception as e:
                LOGGER.warning('  TMDb details error: %s', e)
            time.sleep(sleep_s)
        else:
            LOGGER.info('  TMDb MISS')

        if not omdb_data and not tmdb_id:
            both_miss += 1
            continue

        if not apply:
            continue

        session = get_session(engine)
        try:
            obj = session.get(Movie, movie.id)
            for k, v in {**omdb_fields, **tmdb_fields}.items():
                setattr(obj, k, v)
            obj.enriched_at = datetime.now(timezone.utc)
            session.commit()
            enriched += 1
        except Exception:
            session.rollback()
            LOGGER.exception('  Failed to write enrichment for [%d]', movie.id)
            errors += 1
        finally:
            session.close()

    if apply:
        LOGGER.info('Done — enriched %d, both-missed %d, errors %d', enriched, both_miss, errors)
    else:
        LOGGER.info('DRY-RUN — %d candidates (%d would skip as both-miss)', len(movies) - both_miss, both_miss)


# ── Backfill scraped_title_normalized (Step E.1, kept for reruns) ─────────────

def _fetch_backfill_movies(session, refresh_all: bool, limit: int | None) -> list[Movie]:
    stmt = select(Movie).order_by(Movie.id)
    if not refresh_all:
        stmt = stmt.where(Movie.scraped_title_normalized.is_(None))
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def backfill_normalized_titles(
    apply: bool = False,
    refresh_all: bool = False,
    limit: int | None = None,
) -> None:
    """Compute and write scraped_title_normalized without making any API calls."""
    engine = get_engine()
    session = get_session(engine)
    try:
        movies = _fetch_backfill_movies(session, refresh_all=refresh_all, limit=limit)
    finally:
        session.close()

    if not movies:
        LOGGER.info('No movies to process')
        return

    scope = 'all movies' if refresh_all else 'movies missing scraped_title_normalized'
    LOGGER.info('Processing %d %s', len(movies), scope)
    if not apply:
        LOGGER.info('DRY-RUN — no writes will occur')

    updated = skipped = unchanged = 0
    for movie in movies:
        computed = _api_lookup_title(movie.title or '', movie.scraped_cinema or '')
        if not computed:
            skipped += 1
            continue

        if refresh_all and movie.scraped_title_normalized == computed:
            unchanged += 1
            continue

        LOGGER.info('[%4d] %-60s → %r', movie.id, repr(movie.title), computed)

        if not apply:
            continue

        session = get_session(engine)
        try:
            obj = session.get(Movie, movie.id)
            obj.scraped_title_normalized = computed
            session.commit()
            updated += 1
        except Exception:
            session.rollback()
            LOGGER.exception('Failed to update [%d] %r', movie.id, movie.title)
        finally:
            session.close()

    if apply:
        LOGGER.info('Done — updated %d, unchanged %d, skipped %d', updated, unchanged, skipped)
    elif refresh_all:
        LOGGER.info('DRY-RUN — %d would change, %d unchanged, %d skipped',
                    len(movies) - unchanged - skipped, unchanged, skipped)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Enrich movies with OMDb/TMDb metadata')
    p.add_argument('--apply', action='store_true',
                   help='Write changes to DB (default: dry-run, no writes)')
    p.add_argument('--refresh-all', action='store_true',
                   help='Re-enrich all movies, ignoring enriched_at/release date check')
    p.add_argument('--limit', type=int, default=None,
                   help='Cap number of records processed')
    p.add_argument('--sleep', type=float, default=0.1,
                   help='Seconds between API calls (default: 0.1)')
    p.add_argument('--backfill-titles', action='store_true',
                   help='Only backfill scraped_title_normalized — no API calls')
    p.add_argument('--refresh-count', type=int, default=None, metavar='N',
                   help='Backfill N unenriched movies (full DB, no future-showtime filter)')
    return p


def main(argv=None) -> None:
    args = _build_parser().parse_args(argv)
    if args.backfill_titles:
        backfill_normalized_titles(
            apply=args.apply,
            refresh_all=args.refresh_all,
            limit=args.limit,
        )
    else:
        sync_enrichment(
            apply=args.apply,
            refresh_all=args.refresh_all,
            limit=args.limit,
            sleep_s=args.sleep,
            backfill_count=args.refresh_count,
        )


if __name__ == '__main__':
    main()
