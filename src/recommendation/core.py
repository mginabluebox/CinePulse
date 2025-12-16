import json
import os
import re
import requests
from datetime import date, datetime, timedelta
from sqlalchemy import text
from sqlalchemy.engine import Engine
from database.queries import get_showtimes, get_showtimes_by_ids

def recommend_movies(liked_movies: str, mood: str, db_engine: Engine):
    """
    Fetch showtimes for the next 7 days and call Ollama to recommend up to 5 movies.

    Returns a list of recommendation dicts (same shape as showtimes plus a 'reason' key),
    or an error dict on failure.
    """
    # 1) Query upcoming showtimes (next 7 days)
    try:
        # reuse existing query helper; it returns a list of dicts
        upcoming = get_showtimes(7)

    except Exception as e:
        return f"Error fetching upcoming movies: {e}"

    if not upcoming:
        return "There are no upcoming movies in the next 2 weeks."

    # 3) Build prompt for Ollama
    # Keep the prompt focused and instructive: choose up to 5, only from list, short reasons.
    # Deduplicate by a cleaned title key (normalize case/punctuation) but keep the original
    # title for display. When duplicates exist keep the entry with the earliest show datetime.
    entries = []
    for m in upcoming:
        title_orig = (m.get('title') or '').strip()
        # cleaned title: remove punctuation, collapse whitespace, lowercase
        cleaned = ''.join(ch for ch in title_orig if ch.isalnum() or ch.isspace()).lower().strip()

        # attempt to parse a datetime from showdate + showtime; fall back to date-only ordering
        dt = None
        sd = m.get('showdate')
        st = m.get('showtime')
        if sd:
            if st:
                try:
                    dt = datetime.strptime(f"{sd} {st}", "%Y-%m-%d %I:%M %p")
                except Exception:
                    try:
                        dt = datetime.strptime(f"{sd} {st}", "%Y-%m-%d %H:%M")
                    except Exception:
                        dt = None
            if dt is None:
                try:
                    dt = datetime.strptime(sd, "%Y-%m-%d")
                except Exception:
                    dt = None

        entries.append({
            'cleaned': cleaned,
            'original': title_orig,
            'id': m.get('id'),
            'dt': dt,
            'showdate': sd,
            'showtime': st,
            'cinema': m.get('cinema'),
            'director': m.get('director'),
            'year': m.get('year'),
            'runtime': m.get('runtime'),
            'format': m.get('format'),
            'synopsis': m.get('synopsis'),
            # 'ticket_link': m.get('ticket_link'),
        })

    # pick earliest entry per cleaned title
    best_by_title = {}
    for e in entries:
        key = e['cleaned'] or e['original']
        if key in best_by_title:
            existing = best_by_title[key]
            # compare datetimes when available, else prefer existing (stable)
            if e['dt'] and existing['dt']:
                if e['dt'] < existing['dt']:
                    best_by_title[key] = e
            elif e['dt'] and not existing['dt']:
                best_by_title[key] = e
            # else keep existing
        else:
            best_by_title[key] = e

    # sort by earliest show datetime (entries without dt go to the end)
    candidates = list(best_by_title.values())
    candidates.sort(key=lambda x: x['dt'] if x['dt'] is not None else datetime.max)

    # limit to 10 earliest entries
    selected = candidates[:10]

    # Only include a compact set of fields in the prompt to keep it short:
    # ID, Title, Director, Synopsis
    movies_lines = []
    for i, m in enumerate(selected, 1):
        movies_lines.append(
            f"   ID: {m.get('id') or ''}\n"
            f"   Title: {m['original']}\n"
            f"   Director: {m.get('director') or ''}\n"
            f"   Synopsis: {m.get('synopsis') or ''}\n"
        )
    movies_list_text = "\n".join(movies_lines)

    # print('Movies list for prompt:', movies_list_text)
    prompt = (
        f"You are a helpful cinema recommender. The user recently liked: \"{liked_movies}\" "
        f"and is in the mood for: \"{mood}\".\n\n"
        "Below is a list of movies showing in the next 7 days. Each item includes an ID which is "
        "the database id for that showing.\n\n"
    f"{movies_list_text}\n\n"
    "Task: From the above list, choose up to 5 movies that best match the user's recent likes and "
    "current mood. For each recommended movie return a one-sentence reason. IMPORTANT: Address the user "
    "directly in each reason (use 'you' or 'your' rather than referring to the user in the third person). "
    "Return ONLY a single valid JSON object (no surrounding text) mapping the movie ID to the one-sentence reason. "
    "Example: {\"123\": \"1-2 sentences of reason why this matches your taste.\", \"456\": \"Another 1-2 sentences of reason why this matches your taste.\"}. "
    "If no movies match, return an empty JSON object {}. Do not include any explanations outside the JSON."
    )
    print('Prompt:', prompt)

    # 4) Call Ollama API
    ollama_base = os.getenv("OLLAMA_BASE", "http://localhost:11434/api")
    model_name = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    payload = {
        "model": model_name,
        "prompt": prompt,
        "max_tokens": 512,
        "temperature": 0.7,
        "stream": False
    }

    try:
        resp = requests.post(f"{ollama_base}/generate", json=payload, timeout=30)
    except Exception as e:
        return f"Error calling Ollama API at {ollama_base}/generate: {e}\nCheck that Ollama is running and OLLAMA_BASE/OLLAMA_MODEL are set correctly."

    if resp.status_code == 404:
        return (f"Ollama API returned 404 for model '{model_name}'. "
                "Confirm model name with `curl http://localhost:11434/models` or set OLLAMA_MODEL to a valid model.")

    if not resp.ok:
        return f"Ollama API error: {resp.status_code} {resp.text}"
    
    # 5) Extract the model's response field and parse it as JSON mapping id->reason
    try:
        j = resp.json()
    except Exception:
        # if top-level JSON parse fails, try to parse raw text
        text_content = resp.text
        try:
            parsed = json.loads(text_content)
            if isinstance(parsed, dict):
                j = parsed
            else:
                j = None
        except Exception:
            j = None

    text_content = None
    if isinstance(j, dict):
        # preferred shape: top-level 'response' contains a JSON string mapping ids->reasons
        if 'response' in j and isinstance(j['response'], str):
            text_content = j['response']
        # fallbacks: 'output' or 'result' or 'choices'
        elif 'output' in j and isinstance(j['output'], str):
            text_content = j['output']
        elif 'result' in j and isinstance(j['result'], str):
            text_content = j['result']
        elif 'choices' in j and isinstance(j['choices'], list) and j['choices']:
            choice = j['choices'][0]
            text_content = choice.get('text') or choice.get('content') or None
        else:
            # fallback to stringifying the whole JSON
            try:
                text_content = json.dumps(j)
            except Exception:
                text_content = str(j)
    if not text_content:
        text_content = resp.text

    # Now parse the JSON mapping inside text_content
    parsed_map = None
    try:
        parsed_map = json.loads(text_content)
    except Exception:
        # try extracting a JSON object substring
        m = re.search(r"(\{.*\})", text_content, re.DOTALL)
        if m:
            try:
                parsed_map = json.loads(m.group(1))
            except Exception:
                parsed_map = None

    if not parsed_map or not isinstance(parsed_map, dict):
        return {"error": "could not parse id->reason JSON from model output", "raw": text_content}

    # Normalize keys to ints and collect ids
    id_to_reason = {}
    ids = []
    for k, v in parsed_map.items():
        try:
            ik = int(k)
        except Exception:
            try:
                ik = int(str(k).strip())
            except Exception:
                # skip non-numeric keys
                continue
        id_to_reason[ik] = str(v) if v is not None else ''
        ids.append(ik)

    if not ids:
        return {"error": "model returned no numeric ids", "raw_parsed": parsed_map}

    # Fetch records for these ids from DB and attach reasons
    try:
        rows = get_showtimes_by_ids(ids)
    except Exception as e:
        return {"error": f"database error fetching ids: {e}", "ids": ids}

    # Attach reason to each returned row; preserve ordering by showtime
    recs = []
    for r in rows:
        rid = r.get('id')
        if rid in id_to_reason:
            rr = r.copy()
            rr['reason'] = id_to_reason[rid]
            recs.append(rr)

    # Limit to 5 recommendations
    recs = recs[:5]

    return recs