"""Deduplicate movie records that differ only by format/accessibility suffixes.

One-time / maintenance script — not part of the deployed app. Title normalization
logic lives in src/database/title_normalization.py and is shared with the scraper.

Usage (from repo root):
    python scripts/dedup_movies.py            # dry-run, no writes
    python scripts/dedup_movies.py --apply    # execute merges
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from src.database.models import Movie, Showtime
from src.database.setup_db import get_engine, get_session
from src.database.title_normalization import (
    _api_lookup_title,
    _normalize_for_matching,
    _strip_display_suffix,
)

LOGGER = logging.getLogger('dedup_movies')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


# ── Primary selection ─────────────────────────────────────────────────────────

def _pick_primary(movies: List[Movie], canonical: str) -> Tuple[Movie, List[Movie]]:
    """Return (primary, secondaries).

    Primary is the record whose stored title already equals its canonical form.
    If none qualify (all have suffixes): most recently updated record, then highest id.
    """
    clean = [m for m in movies if _normalize_for_matching(m.title) == canonical
             and m.title.lower().strip() == canonical]
    if clean:
        primary = min(clean, key=lambda m: m.id)
    else:
        primary = max(movies, key=lambda m: (m.updated_at or m.created_at, m.id))
    secondaries = [m for m in movies if m.id != primary.id]
    return primary, secondaries


# ── Enrichment field names shared between null-year merge helpers ─────────────

_ENRICHMENT_FIELDS = [
    'tmdb_id', 'imdb_id', 'imdb_rating', 'imdb_votes',
    'omdb_rt_score', 'omdb_metacritic_score',
    'tmdb_original_title', 'tmdb_genres', 'tmdb_origin_countries',
    'tmdb_original_language', 'tmdb_spoken_languages', 'tmdb_tagline',
    'tmdb_overview', 'tmdb_runtime', 'tmdb_collection_name',
    'tmdb_poster_url', 'tmdb_release_date', 'tmdb_trailer_url',
    'tmdb_title_zh', 'embedding', 'embedding_model',
    'embedding_source_hash', 'enriched_at', 'embedded_at',
]


def _copy_enrichment(src: Movie, dst: Movie) -> None:
    """Copy enrichment fields from src → dst where dst field is None."""
    for field in _ENRICHMENT_FIELDS:
        if getattr(dst, field) is None and getattr(src, field) is not None:
            setattr(dst, field, getattr(src, field))


# ── Main dedup logic ──────────────────────────────────────────────────────────

def dedup_movies(apply: bool = False, limit: int | None = None) -> None:
    engine = get_engine()
    session = get_session(engine)
    try:
        movies: List[Movie] = session.query(Movie).all()
    finally:
        session.close()

    # Group by (canonical_title, year)
    groups: dict[tuple, List[Movie]] = defaultdict(list)
    for m in movies:
        canonical = _normalize_for_matching(m.title)
        groups[(canonical, m.year)].append(m)

    dup_groups = [(k, v) for k, v in groups.items() if len(v) > 1]

    # Null-year duplicates: same canonical title, one record has year=None, another has a year
    by_canonical: dict[str, list[Movie]] = defaultdict(list)
    for m in movies:
        by_canonical[_normalize_for_matching(m.title)].append(m)

    null_year_pairs: List[Tuple[Movie, Movie]] = []  # (null_record, year_record)
    for canonical, ms in by_canonical.items():
        null_ms = [m for m in ms if m.year is None]
        year_ms = [m for m in ms if m.year is not None]
        if not null_ms or not year_ms:
            continue
        # Pick the year record with the most recent update as the keeper
        keeper = max(year_ms, key=lambda m: (m.updated_at or m.created_at, m.id))
        for null_m in null_ms:
            null_year_pairs.append((null_m, keeper))

    # Film Forum standalone cleanups: suffix in title but no duplicate record exists
    dup_canonicals = {k[0] for k, _ in dup_groups}
    ff_cleanups: List[Movie] = []
    for m in movies:
        if 'FILM FORUM' not in (m.scraped_cinema or '').upper():
            continue
        canonical = _normalize_for_matching(m.title)
        if canonical != m.title.lower().strip() and canonical not in dup_canonicals:
            ff_cleanups.append(m)

    if limit:
        dup_groups = dup_groups[:limit]

    LOGGER.info(
        'Found %d duplicate group(s), %d null-year pair(s), %d Film Forum title cleanup(s)',
        len(dup_groups), len(null_year_pairs), len(ff_cleanups),
    )
    if not apply:
        LOGGER.info('DRY-RUN — no writes will occur')

    # ── Duplicate groups ───────────────────────────────────────────────────────
    for (canonical, year), group_movies in dup_groups:
        primary, secondaries = _pick_primary(group_movies, canonical)
        print(f"\nGroup  canonical='{canonical}'  year={year}")
        primary_display = _strip_display_suffix(primary.title)
        title_note = (
            f" → will clean to '{primary_display}'"
            if _normalize_for_matching(primary.title) != primary.title.lower().strip()
            or primary.title != primary_display
            else ''
        )
        print(f"  PRIMARY   [{primary.id:4d}] '{primary.title}'{title_note}  (cinema: {primary.scraped_cinema})")
        for s in secondaries:
            print(f"  SECONDARY [{s.id:4d}] '{s.title}'  (cinema: {s.scraped_cinema})")

        if not apply:
            continue

        session = get_session(engine)
        try:
            primary_obj = session.get(Movie, primary.id)
            primary_obj.scraped_title_normalized = _api_lookup_title(
                primary_obj.title, primary_obj.scraped_cinema or '',
            )
            # Clean primary title if it still has a suffix or non-normalized whitespace
            clean_title = _strip_display_suffix(primary_obj.title)
            if primary_obj.title != clean_title:
                LOGGER.info(
                    "Cleaned primary title [%d]: '%s' → '%s'",
                    primary.id, primary_obj.title, clean_title,
                )
                primary_obj.title = clean_title

            for sec in secondaries:
                # Build the set of (show_time, cinema, format) already on the primary
                primary_keys = {
                    (st.show_time, st.cinema, st.format)
                    for st in session.query(Showtime).filter(
                        Showtime.movie_id == primary.id
                    ).all()
                }

                # Delete secondary showtimes that would violate the unique constraint
                conflicts = [
                    st for st in session.query(Showtime).filter(
                        Showtime.movie_id == sec.id
                    ).all()
                    if (st.show_time, st.cinema, st.format) in primary_keys
                ]
                for st in conflicts:
                    session.delete(st)
                if conflicts:
                    session.flush()
                    LOGGER.info(
                        "Deleted %d conflicting showtime(s) from secondary [%d]",
                        len(conflicts), sec.id,
                    )

                session.query(Showtime).filter(
                    Showtime.movie_id == sec.id
                ).update({'movie_id': primary.id})
                session.delete(session.get(Movie, sec.id))
                LOGGER.info(
                    "Merged [%d] '%s' → [%d] '%s'",
                    sec.id, sec.title, primary.id, primary.title,
                )

            session.commit()
        except Exception:
            session.rollback()
            LOGGER.exception("Failed to merge group '%s' — rolled back", canonical)
        finally:
            session.close()

    # ── Null-year merges ───────────────────────────────────────────────────────
    for null_m, keeper in null_year_pairs:
        print(
            f"\nNull-year  [{null_m.id:4d}] '{null_m.title}'  year=None  (cinema: {null_m.scraped_cinema})"
            f"\n  → KEEP   [{keeper.id:4d}] '{keeper.title}'  year={keeper.year}  (cinema: {keeper.scraped_cinema})"
        )

        if not apply:
            continue

        session = get_session(engine)
        try:
            null_obj = session.get(Movie, null_m.id)
            keep_obj = session.get(Movie, keeper.id)

            _copy_enrichment(src=null_obj, dst=keep_obj)

            # Resolve showtime conflicts before reassigning
            keep_keys = {
                (st.show_time, st.cinema, st.format)
                for st in session.query(Showtime).filter(Showtime.movie_id == keep_obj.id).all()
            }
            conflicts = [
                st for st in session.query(Showtime).filter(Showtime.movie_id == null_obj.id).all()
                if (st.show_time, st.cinema, st.format) in keep_keys
            ]
            for st in conflicts:
                session.delete(st)
            if conflicts:
                session.flush()
                LOGGER.info("Deleted %d conflicting showtime(s) from null-year [%d]", len(conflicts), null_m.id)

            session.query(Showtime).filter(
                Showtime.movie_id == null_obj.id
            ).update({'movie_id': keep_obj.id})
            session.delete(null_obj)
            session.commit()
            LOGGER.info("Merged null-year [%d] → [%d] '%s'", null_m.id, keeper.id, keeper.title)
        except Exception:
            session.rollback()
            LOGGER.exception("Failed to merge null-year [%d] — rolled back", null_m.id)
        finally:
            session.close()

    # ── Film Forum title cleanups ──────────────────────────────────────────────
    for m in ff_cleanups:
        display = _strip_display_suffix(m.title)
        print(f"\nFilm Forum cleanup: [{m.id}] '{m.title}' → '{display}'")

        if not apply:
            continue

        session = get_session(engine)
        try:
            obj = session.get(Movie, m.id)
            original_title = obj.title
            obj.title = display
            obj.scraped_title_normalized = _api_lookup_title(display, obj.scraped_cinema or '')
            session.commit()
            LOGGER.info(
                "Cleaned up Film Forum title [%d]: '%s' → '%s'",
                m.id, original_title, display,
            )
        except Exception:
            session.rollback()
            LOGGER.exception("Failed to clean up [%d] '%s'", m.id, m.title)
        finally:
            session.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Deduplicate movie records')
    parser.add_argument('--apply', action='store_true',
                        help='Execute merges (default: dry-run, no writes)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Cap number of duplicate groups processed')
    return parser


def main(argv=None) -> None:
    args = _build_parser().parse_args(argv)
    dedup_movies(apply=args.apply, limit=args.limit)


if __name__ == '__main__':
    main()
