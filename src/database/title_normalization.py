"""Title normalization helpers shared across the scraper pipeline and enrichment.

Pure string logic — no DB or environment dependencies — so it imports cleanly in
both the web-app context (``database.title_normalization``) and the scraper/script
context (``src.database.title_normalization``).

Imported by:
  - scrapers/pipelines.py            (_normalize_whitespace, _api_lookup_title, _strip_display_suffix)
  - src/database/sync_enrichment.py  (_api_lookup_title)
  - scripts/dedup_movies.py          (_normalize_for_matching, _strip_display_suffix, _api_lookup_title)
"""
from __future__ import annotations

import re
import unicodedata

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


def _is_all_caps_word(word: str) -> bool:
    """True if word has ≥1 uppercase letter and zero lowercase letters."""
    return any(c.isupper() for c in word) and not any(c.islower() for c in word)


def _strip_display_suffix(title: str) -> str:
    """Strip format suffix and normalize whitespace, preserving original casing."""
    t = _normalize_whitespace((title or '').strip())
    t = _PAREN_SUFFIX.sub('', t).strip()
    t = _BRACKET_SUFFIX.sub('', t).strip()
    t = _FORMAT_SUFFIX.sub('', t).strip()
    return t


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


def _normalize_for_matching(title: str) -> str:
    """Apply all rules unconditionally for cross-cinema duplicate detection."""
    return _strip_display_suffix(title).lower()
