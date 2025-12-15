from datetime import date, datetime, timedelta
import json
import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine
import os
from database.queries import get_showtimes

def recommend_movies(liked_movies: str, mood: str, db_engine: Engine) -> str:
    """
    Fetch showtimes for the next 7 days from the `showtimes` table and call Ollama to
    recommend up to 5 movies from that list based on liked_movies and mood.
    Returns the LLM response (string). Handles empty upcoming list gracefully.
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
    movies_lines = []
    for i, m in enumerate(upcoming, 1):
        movies_lines.append(
            f"{i}. Title: {m.get('title')}\n"
            f"   Date: {m.get('showdate')} {m.get('showtime')}\n"
            f"   Cinema: {m.get('cinema')}\n"
            f"   Director: {m.get('director')}\n"
            f"   Year: {m.get('year')}\n"
            f"   Runtime: {m.get('runtime')}\n"
            f"   Format: {m.get('format')}\n"
            f"   Synopsis: {m.get('synopsis')}\n"
            f"   Ticket: {m.get('ticket_link')}"
        )
    movies_list_text = "\n\n".join(movies_lines)

    print('Movies list for prompt:', movies_list_text)
    prompt = (
        f"You are a helpful cinema recommender. The user recently liked: \"{liked_movies}\" "
        f"and is in the mood for: \"{mood}\".\n\n"
        "Below is a list of movies showing in the next 2 weeks:\n\n"
        f"{movies_list_text}\n\n"
        "Task: Recommend up to 5 movies ONLY from the above list. For each recommended movie, "
        "give a one-sentence explanation why it matches the user's recent likes and current mood. "
        "Number each recommendation. If none match, say so briefly. Keep the answer concise."
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
    
    # 5) Return LLM response as string. Try to parse common fields.
    try:
        j = resp.json()
    except Exception:
        return resp.text

    # Ollama responses vary; attempt to extract likely text fields
    if isinstance(j, dict):
        # common possibilities: 'choices' -> [{'text':...}] or 'output' or 'result'
        if "choices" in j and isinstance(j["choices"], list) and j["choices"]:
            choice = j["choices"][0]
            # choice may contain 'text' or 'content'
            return choice.get("text") or choice.get("content") or json.dumps(choice)
        if "output" in j:
            return j["output"]
        if "result" in j:
            return j["result"]
        # fallback: return whole json as pretty string
        return json.dumps(j, ensure_ascii=False, indent=2)

    return str(j)