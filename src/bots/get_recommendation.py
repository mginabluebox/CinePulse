import json
import math
import re
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.engine import Engine
from database.queries import (
    get_showtimes,
    get_showtimes_by_ids,
    get_movies_with_future_showtimes,
    get_future_showtimes_for_movie_ids,
)
from .llm_selector import call_llm, generate_embedding
from errors import LLMError, DBError, ParseError


def _clean_title(title: str) -> str:
    return ''.join(ch for ch in (title or '') if ch.isalnum() or ch.isspace()).lower().strip()


def _parse_show_datetime(showdate: str, showtime: str):
    if not showdate:
        return None
    if showtime:
        for fmt in ("%Y-%m-%d %I:%M %p", 
                    "%Y-%m-%d %H:%M"):
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
        # skip entries where tickets are sold out
        ticket_link = (m.get('ticket_link') or '')
        if isinstance(ticket_link, str) and ticket_link.strip().lower() == 'sold_out':
            continue

        title_orig = (m.get('title') or '').strip()
        cleaned = _clean_title(title_orig)
        dt = _parse_show_datetime(m.get('showdate'), m.get('showtime'))
        entries.append({
            'cleaned': cleaned,
            'original': title_orig,
            'ticket_link': ticket_link,
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
            'image_url': m.get('image_url'),
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


def fetch_showtimes(days: int = 7, limit: int = 15, engine=None):
    """Fetch showtimes from the DB and return up to `limit` candidate rows (deduped and ordered)."""
    try:
        # allow callers to provide an engine via DI
        raw = get_showtimes(interval_days=days, engine=engine)
    except Exception as e:
        raise DBError(f"Error fetching upcoming movies: {e}")

    if not raw:
        return []

    candidates = _dedupe_rows(raw)
    return candidates[:limit]


def build_prompt(mood: str, candidates, days: int = 7) -> str:
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
        f"You are a movie recommender. The user is in the mood for: \"{mood}\".\n\n"
        f"Below is a list of movies showing in the next {days} days. Each item includes only the ID, Title, "
        f"Director, and Synopsis (the ID is the database id for that showing).\n\n"
        f"{movies_list_text}\n\n"
        "Task: From the above list, choose at least 5 movies that best match the user's recent likes and "
        "current mood. For each recommended movie return a one-sentence reason. IMPORTANT: Address the user "
        "directly in each reason (use 'you' or 'your' rather than referring to the user in the third person). "
        "Return ONLY a single valid JSON object (no surrounding text) mapping the movie ID to the one-sentence reason. "
        "Example: {\"123\": \"1-2 sentences of reason why this matches your taste.\", \"456\": \"Another 1-2 sentences of reason why this matches your taste.\"}. "
        "If no movies match, return an empty JSON object {}. Do not include any explanations outside the JSON."
    )
    return prompt

# Backwards-compatibility for older tests/imports
_build_prompt = build_prompt

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


def recommend_movies(mood: str, db_engine: Engine = None, log_calls: bool = True):
    """High-level orchestration: fetch showtimes, build prompt & call LLM, parse response."""
    
    # Step 1: fetch and dedupe showtimes (may raise on DB error)
    candidates = fetch_showtimes(days=7, limit=15, engine=db_engine)
    if not candidates:
        return []

    # Step 2: build prompt and call LLM (may raise on LLM/provider error)
    prompt = build_prompt(mood, candidates, days=7)
    text_content = call_llm(prompt, max_tokens=512, temperature=0.7, log_calls=log_calls)

    # Step 3: parse response and return recommended rows (may raise on parsing/db lookup errors)
    recs = parse_response(text_content, engine=db_engine)
    return recs


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _group_showtimes_by_cinema(showtimes: List[Dict[str, Any]]):
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for st in showtimes:
        cinema = st.get('cinema') or 'Unknown'
        grouped.setdefault(cinema, []).append(st)
    # preserve chronological order within each cinema
    for cinema, rows in grouped.items():
        grouped[cinema] = rows
    return grouped


def _score_candidates_by_similarity(query_vec: List[float], candidates: List[Dict[str, Any]], top_n: int = 30):
    scored = []
    for c in candidates:
        embedding_list = [float(x) for x in (c.get('embedding') or [])]
        if not embedding_list:
            continue
        sim = float(_cosine_similarity(query_vec, embedding_list))
        scored.append({**c, 'similarity': sim})

    scored.sort(key=lambda x: x['similarity'], reverse=True)
    return scored[:top_n]


def build_movie_prompt(mood: str, candidates: List[Dict[str, Any]]) -> str:
    def _truncate(s: str, n: int = 300) -> str:
        if not s:
            return ''
        s = str(s)
        return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + '...'

    movies_lines = []
    for m in candidates:
        synopsis = _truncate(m.get('synopsis') or '', 300)
        movies_lines.append(
            f"MovieID: {m.get('movie_id') or ''}  Title: {m.get('title') or ''}\n"
            f"   Director: {m.get('director') or ''}\n"
            f"   Synopsis: {synopsis}\n"
        )
    movies_list_text = "\n\n".join(movies_lines)

    prompt = (
        f"You are a movie recommender. The user mood is: \"{mood}\".\n\n"
        f"Below is a list of candidate movies that have upcoming showtimes. Each item includes MovieID, Title, Director, and Synopsis.\n\n"
        f"{movies_list_text}\n\n"
        "Task: From the above list, choose at least 5 movies that best match the user's mood. For each recommended movie, return a one-sentence reason. "
        "IMPORTANT: Use the MovieID as the JSON key. Address the user directly in each reason. Return ONLY a valid JSON object (no extra text) mapping MovieID -> reason. "
        "Example: {\"123\": \"1-2 sentences of reason.\", \"456\": \"Another 1-2 sentences.\"}. If no movies match, return {}."
    )
    return prompt


def _parse_movie_reason_map(text_content: str) -> Dict[int, str]:
    parsed_map = _extract_json_object(text_content)
    if not parsed_map or not isinstance(parsed_map, dict):
        raise ParseError("could not parse movie id->reason JSON from model output")

    id_to_reason: Dict[int, str] = {}
    for k, v in parsed_map.items():
        try:
            ik = int(k)
        except Exception:
            try:
                ik = int(str(k).strip())
            except Exception:
                continue
        id_to_reason[ik] = str(v) if v is not None else ''

    if not id_to_reason:
        raise ParseError("model returned no numeric movie ids")

    return id_to_reason


def recommend_movies_by_embedding(mood: str, db_engine: Engine = None,
                                  candidate_pool: int = 30,
                                  top_k: int = 5,
                                  showtimes_per_movie: int = 5,
                                  log_calls: bool = True):
    """Recommend movies using embedding similarity and return movie-level cards.

    Flow:
    1) Fetch all movies that still have future showtimes (with embeddings).
    2) Embed the user's mood/query once and score all candidates by cosine similarity.
    3) Take the top 30 by similarity and ask the LLM to pick the best 5 with reasons.
    4) Fetch up to 5 upcoming showtimes for the LLM-selected movies (earliest→latest).
    """

    # Step 1: fetch all eligible candidates (future showtimes + embedding)
    candidates = get_movies_with_future_showtimes(engine=db_engine)
    candidates = [c for c in candidates if c.get('embedding')]
    if not candidates:
        return []

    # Step 2: embed the user query
    query_vec_raw = generate_embedding(mood)
    query_vec = [float(x) for x in (query_vec_raw or [])]
    if not query_vec:
        return []

    # Step 3: score all candidates and keep top N for LLM
    top_scored = _score_candidates_by_similarity(query_vec, candidates, top_n=candidate_pool)
    if not top_scored:
        return []

    # Step 4: ask LLM to pick the best subset (up to 5)
    prompt = build_movie_prompt(mood, top_scored)
    text_content = call_llm(prompt, max_tokens=512, temperature=0.7, log_calls=log_calls)
    id_to_reason = _parse_movie_reason_map(text_content)

    # Preserve LLM order, cap at 5
    id_reason_pairs = []
    seen_ids = set()
    for mid, reason in id_to_reason.items():
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        id_reason_pairs.append((mid, reason))
    id_reason_pairs = id_reason_pairs[:top_k]

    candidate_lookup = {c['movie_id']: c for c in top_scored}
    selected_ids = [mid for (mid, _) in id_reason_pairs if mid in candidate_lookup]
    if not selected_ids:
        return []

    # Step 5: fetch showtimes (future only, earliest first, capped)
    showtime_map = get_future_showtimes_for_movie_ids(selected_ids, limit_per_movie=showtimes_per_movie, engine=db_engine)

    results = []
    for mid, reason in id_reason_pairs:
        meta = candidate_lookup.get(mid)
        st_list = showtime_map.get(mid, [])
        if not meta or not st_list:
            continue

        grouped = _group_showtimes_by_cinema(st_list)
        cinemas_payload = [
            {
                'cinema': cinema,
                'showtimes': rows,
            }
            for cinema, rows in grouped.items()
        ]

        similarity_score = float(meta.get('similarity', 0.0))
        poster_url = meta.get('scraped_image_url') or next((s.get('image_url') for s in st_list if s.get('image_url')), None)
        results.append({
            'id': mid,  # for swipe handling on the frontend
            'movie_id': mid,
            'title': meta.get('title'),
            'year': meta.get('year'),
            'director': meta.get('director'),
            'synopsis': meta.get('synopsis'),
            'similarity': similarity_score,
            'reason': reason,
            'showtimes': st_list,
            'cinemas': cinemas_payload,
            'scraped_image_url': poster_url,
        })

    return results