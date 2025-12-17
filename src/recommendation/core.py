import json
import os
import re
from datetime import datetime
from sqlalchemy.engine import Engine
from database.queries import get_showtimes, get_showtimes_by_ids
from .llm import call_llm
from errors import LLMError, DBError, ParseError


def _clean_title(title: str) -> str:
    return ''.join(ch for ch in (title or '') if ch.isalnum() or ch.isspace()).lower().strip()


def _parse_show_datetime(showdate: str, showtime: str):
    if not showdate:
        return None
    if showtime:
        for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(f"{showdate} {showtime}", fmt)
            except Exception:
                continue
    try:
        return datetime.strptime(showdate, "%Y-%m-%d")
    except Exception:
        return None


def _dedupe_rows(rows):
    """Return a list of deduped rows keeping the earliest showing per cleaned title."""
    entries = []
    for m in rows:
        title_orig = (m.get('title') or '').strip()
        cleaned = _clean_title(title_orig)
        dt = _parse_show_datetime(m.get('showdate'), m.get('showtime'))
        entries.append({
            'cleaned': cleaned,
            'original': title_orig,
            'id': m.get('id'),
            'dt': dt,
            'showdate': m.get('showdate'),
            'showtime': m.get('showtime'),
            'cinema': m.get('cinema'),
            'director': m.get('director'),
            'year': m.get('year'),
            'runtime': m.get('runtime'),
            'format': m.get('format'),
            'synopsis': m.get('synopsis'),
        })

    best_by_title = {}
    for e in entries:
        key = e['cleaned'] or e['original']
        if key in best_by_title:
            existing = best_by_title[key]
            if e['dt'] and existing['dt']:
                if e['dt'] < existing['dt']:
                    best_by_title[key] = e
            elif e['dt'] and not existing['dt']:
                best_by_title[key] = e
        else:
            best_by_title[key] = e

    candidates = list(best_by_title.values())
    candidates.sort(key=lambda x: x['dt'] if x['dt'] is not None else datetime.max)
    return candidates


def fetch_showtimes(days: int = 7, limit: int = 10, engine=None):
    """Fetch showtimes from the DB and return up to `limit` candidate rows (deduped and ordered)."""
    try:
        # allow callers to provide an engine via DI
        raw = get_showtimes(days, engine=engine)
    except Exception as e:
        raise DBError(f"Error fetching upcoming movies: {e}")

    if not raw:
        return []

    candidates = _dedupe_rows(raw)
    return candidates[:limit]


def _build_prompt(liked_movies: str, mood: str, candidates, days: int = 7) -> str:
    # Build a compact movies list text with only id, title, director, synopsis
    def _truncate(s: str, n: int = 300) -> str:
        if not s:
            return ''
        s = str(s)
        return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + '...'

    movies_lines = []
    for i, m in enumerate(candidates, 1):
        synopsis = _truncate(m.get('synopsis') or '', 300)
        movies_lines.append(
            f"{i}. ID: {m.get('id') or ''}  Title: {m['original']}\n"
            f"   Director: {m.get('director') or ''}\n"
            f"   Synopsis: {synopsis}\n"
        )
    movies_list_text = "\n\n".join(movies_lines)

    prompt = (
        f"You are a helpful cinema recommender. The user recently liked: \"{liked_movies}\" "
        f"and is in the mood for: \"{mood}\".\n\n"
        f"Below is a list of movies showing in the next {days} days. Each item includes only the ID, Title, "
        f"Director, and Synopsis (the ID is the database id for that showing).\n\n"
        f"{movies_list_text}\n\n"
        "Task: From the above list, choose up to 5 movies that best match the user's recent likes and "
        "current mood. For each recommended movie return a one-sentence reason. IMPORTANT: Address the user "
        "directly in each reason (use 'you' or 'your' rather than referring to the user in the third person). "
        "Return ONLY a single valid JSON object (no surrounding text) mapping the movie ID to the one-sentence reason. "
        "Example: {\"123\": \"1-2 sentences of reason why this matches your taste.\", \"456\": \"Another 1-2 sentences of reason why this matches your taste.\"}. "
        "If no movies match, return an empty JSON object {}. Do not include any explanations outside the JSON."
    )
    return prompt


def get_llm_response(liked_movies: str, mood: str, candidates, provider: str = None, max_tokens: int = 512, temperature: float = 0.7, days: int = 7) -> str:
    """Build the prompt from inputs and call the configured LLM provider.

    This centralizes prompt construction so callers only pass high-level inputs.
    """
    prompt = _build_prompt(liked_movies, mood, candidates, days=days)
    try:
        return call_llm(prompt, provider=provider, max_tokens=max_tokens, temperature=temperature)
    except Exception as e:
        # Wrap or re-raise as LLMError for the HTTP boundary to map to 502
        raise LLMError(f"LLM provider error: {e}") from e


def _extract_json_object(text: str):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
    return None


def parse_response(text_content: str, engine=None):
    parsed_map = _extract_json_object(text_content)
    if not parsed_map or not isinstance(parsed_map, dict):
        raise ParseError("could not parse id->reason JSON from model output")

    id_to_reason = {}
    ids = []
    for k, v in parsed_map.items():
        try:
            ik = int(k)
        except Exception:
            try:
                ik = int(str(k).strip())
            except Exception:
                continue
        id_to_reason[ik] = str(v) if v is not None else ''
        ids.append(ik)

    if not ids:
        raise ValueError("model returned no numeric ids")

    try:
        rows = get_showtimes_by_ids(ids, engine=engine)
    except Exception as e:
        raise DBError(f"database error fetching ids: {e}")

    recs = []
    for r in rows:
        rid = r.get('id')
        if rid in id_to_reason:
            rr = r.copy()
            rr['reason'] = id_to_reason[rid]
            recs.append(rr)

    return recs[:5]


def recommend_movies(liked_movies: str, mood: str, db_engine: Engine = None):
    """High-level orchestration: fetch showtimes, build prompt & call LLM, parse response."""
    # Step 1: fetch and dedupe showtimes (may raise on DB error)
    candidates = fetch_showtimes(days=7, limit=10, engine=db_engine)
    if not candidates:
        return []

    # Step 2: build prompt and call LLM (may raise on LLM/provider error)
    provider = os.getenv('LLM_PROVIDER')
    text_content = get_llm_response(liked_movies, mood, candidates, provider=provider, max_tokens=512, temperature=0.7, days=7)

    # Step 3: parse response and return recommended rows (may raise on parsing/db lookup errors)
    recs = parse_response(text_content, engine=db_engine)
    return recs