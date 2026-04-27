"""Deduplicate movie records that differ only by format/accessibility suffixes.

Usage (from repo root):
    python src/database/dedup_movies.py            # dry-run, no writes
    python src/database/dedup_movies.py --apply    # execute merges
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from src.database.models import Movie, Showtime
from src.database.setup_db import get_engine, get_session

LOGGER = logging.getLogger('dedup_movies')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

# ── Whitelist regexes ──────────────────────────────────────────────────────────

_PAREN_SUFFIX = re.compile(
    r'\s*\(\s*open\s*captioning\s*\)\s*$',
    flags=re.IGNORECASE,
)
_BRACKET_SUFFIX = re.compile(
    r'\s*\[\s*(?:35mm|16mm|70mm|dcp|digital|ov)\s*\]\s*$',
    flags=re.IGNORECASE,
)
_FORMAT_SUFFIX = re.compile(
    r'\s+in\s+(?:16|35|70)mm\s*$',
    flags=re.IGNORECASE,
)

# All cinemas: "X presents: TITLE" prefix (6 known records across Metrograph, IFC CENTER)
_PRESENTS_PREFIX_RE = re.compile(r'^.+?\bpresents:?\s+', re.IGNORECASE)

# Metrograph-only: "X selects TITLE" prefix — API lookup only
_METROGRAPH_SELECTS_RE = re.compile(r'^.+?\bselects\s+', re.IGNORECASE)

# Metrograph-only: "TITLE preceded by OTHER TITLE" — keep first title for API lookup
_METROGRAPH_PRECEDED_BY_RE = re.compile(r'\s+preceded\s+by\s+.+$', re.IGNORECASE)


def _normalize_whitespace(t: str) -> str:
    """Normalize unicode whitespace (e.g. \xa0 non-breaking space) to plain spaces."""
    t = unicodedata.normalize('NFKC', t)
    return ' '.join(t.split())


# ── Normalization (also imported by scrapers/pipelines.py) ────────────────────

def _is_all_caps_word(word: str) -> bool:
    """True if word has ≥1 uppercase letter and zero lowercase letters."""
    return any(c.isupper() for c in word) and not any(c.islower() for c in word)


def _api_lookup_title(title: str, cinema: str = '') -> str:
    """Return title normalized for OMDb/TMDb API lookups.

    Composes _strip_display_suffix (access/format suffix removal) with
    API-specific rules that are mutually exclusive from dedup normalization:
      - All cinemas: strip "X presents:" prefix
      - Film Forum: extract all-caps film title from director-credit format
        (e.g. "Spike Lee's CROOKLYN" → "CROOKLYN")

    Returns with original casing preserved (APIs are case-insensitive).
    """
    # _strip_display_suffix handles whitespace normalization and suffix stripping —
    # those rules are not repeated here to avoid double-applying them.
    t = _strip_display_suffix(title)
    t = _PRESENTS_PREFIX_RE.sub('', t).strip()
    if 'METROGRAPH' in cinema.upper():
        t = _METROGRAPH_SELECTS_RE.sub('', t).strip()
        t = _METROGRAPH_PRECEDED_BY_RE.sub('', t).strip()
    if 'FILM FORUM' in cinema.upper():
        # Normalize curly apostrophes (U+2018/U+2019) scraped from Film Forum to
        # straight apostrophe so OMDb lookup matches (e.g. BERNSTEIN’S WALL)
        t = t.replace('’', "'").replace('‘', "'")
        words = t.split()
        mixed_case_words = [w for w in words if any(c.islower() for c in w)]
        # Only extract when ≥2 mixed-case words — prevents false positives on
        # all-caps titles (BERNSTEIN'S WALL) and near-all-caps like
        # "MAD BILLS TO PAY (or DESTINY...)" which has only one lowercase word.
        if len(mixed_case_words) > 1:
            runs: list[str] = []
            current: list[str] = []
            for w in words:
                if _is_all_caps_word(w):
                    current.append(w)
                else:
                    if current:
                        runs.append(' '.join(current))
                        current = []
            if current:
                runs.append(' '.join(current))
            # Use LAST run to skip abbreviations like (YFF) that precede the real title
            if runs:
                last_run = runs[-1]
                if last_run != t:
                    t = last_run
    return t


def _scraped_title_normalized(title: str, cinema: str = '') -> str:
    """Return lowercase canonical title applying cinema-specific rules.

    Used by pipelines.py to route scraped items to the correct movie record.
    Only rules confirmed for that cinema are applied.
    """
    t = _normalize_whitespace((title or '').strip())
    t = _PAREN_SUFFIX.sub('', t).strip()
    if 'METROGRAPH' in cinema.upper():
        t = _BRACKET_SUFFIX.sub('', t).strip()
    if 'FILM FORUM' in cinema.upper():
        t = _FORMAT_SUFFIX.sub('', t).strip()
    return t.lower()


def _normalize_for_matching(title: str) -> str:
    """Apply all rules unconditionally for cross-cinema duplicate detection."""
    return _strip_display_suffix(title).lower()


def _strip_display_suffix(title: str) -> str:
    """Strip format suffix and normalize whitespace, preserving original casing."""
    t = _normalize_whitespace((title or '').strip())
    t = _PAREN_SUFFIX.sub('', t).strip()
    t = _BRACKET_SUFFIX.sub('', t).strip()
    t = _FORMAT_SUFFIX.sub('', t).strip()
    return t


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
        'Found %d duplicate group(s) and %d Film Forum title cleanup(s)',
        len(dup_groups), len(ff_cleanups),
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
