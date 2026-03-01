import os
import json
import requests
from openai import OpenAI
import tiktoken

from errors import LLMError
from database.setup_db import get_engine
from database.queries import insert_recommendation_log

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

if LLM_PROVIDER == "openai":
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
elif LLM_PROVIDER == "ollama":
    OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434/api")
    MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
else:
    raise RuntimeError("LLM_PROVIDER must be either 'openai' or 'ollama'")

OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

DEFAULT_OPENAI_TIMEOUT = 30
DEFAULT_OLLAMA_TIMEOUT = 30

def openai_generate(prompt: str, model: str, 
                    max_tokens: int = 512, 
                    temperature: float = 0.7):
    """
    Call OpenAI via the official Python client and return the assistant text.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Make request - let exceptions propagate to caller
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user", 
                "content": prompt
            }
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )

    # Common response shapes: prefer chat.message.content, then text
    if hasattr(resp, "choices") and resp.choices:
        choice = resp.choices[0]
        msg = getattr(choice, "message", None)
        if msg:
            if isinstance(msg, dict):
                return msg.get("content", "")
            return getattr(msg, "content", "")

        # fallback for dict-like choices
        if isinstance(choice, dict):
            return choice.get("message", {}).get("content") if choice.get("message") else choice.get("text") or ""

    return str(resp)


def ollama_generate(prompt: str, model: str, 
                    max_tokens: int = 512, 
                    temperature: float = 0.7):
    """
    Call Ollama local HTTP API and return the response text (handles common response shapes).
    """

    payload = {
        "model": model, 
        "prompt": prompt, 
        "max_tokens": max_tokens, 
        "temperature": temperature, 
        "stream": False
    }
    resp = requests.post(f"{OLLAMA_BASE}/generate", json=payload, timeout=DEFAULT_OLLAMA_TIMEOUT)
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        return resp.text

    if isinstance(data, dict):
        for key in ("response", "output", "result"):
            if key in data and isinstance(data[key], str):
                return data[key]

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                return choice.get("text") or choice.get("content") or json.dumps(choice)
            return str(choice)

    return resp.text


def call_llm(prompt: str, 
             max_tokens: int = 512, 
             temperature: float = 0.7):
    """Dispatch to the configured LLM provider. Provider can be 'openai' or 'ollama'.

    Retries once on error with a short backoff.
    Returns the raw text content from the model.
    """

    def _count_tokens(text: str, model: str = None) -> int:
        
        enc = tiktoken.get_encoding('o200k_base')
        
        return len(enc.encode(text))

        # # fallback heuristic: average 4 chars per token
        # return max(1, len(text) // 4)

    # ensure we count tokens using a concrete model name
    prompt_tokens = _count_tokens(prompt, MODEL_NAME)

    try:
        if LLM_PROVIDER == "openai":
            # print("Calling OpenAI LLM...") 
            resp = openai_generate(prompt, MODEL_NAME, max_tokens=max_tokens, temperature=temperature)
        elif LLM_PROVIDER == "ollama":
            # print("Calling Ollama LLM...") 
            resp = ollama_generate(prompt, MODEL_NAME, max_tokens=max_tokens, temperature=temperature)

        # log successful call (error_code 0)
        try:
            engine = get_engine()
            insert_recommendation_log(
                queried_at="now()",
                api_name=LLM_PROVIDER,
                model_name=MODEL_NAME or '',
                prompt_num_token=prompt_tokens,
                prompt=prompt,
                response=resp if isinstance(resp, str) else json.dumps(resp),
                error_code=0,
                engine=engine,
            )
        except Exception:
            # logging should not break normal flow
            pass

        return resp
    except Exception as e:
        # log the failure and raise an LLMError
        try:
            engine = get_engine()
            insert_recommendation_log(
                queried_at="now()",
                api_name=LLM_PROVIDER,
                model_name=MODEL_NAME or '',
                prompt_num_token=prompt_tokens,
                prompt=prompt,
                response=str(e),
                error_code=1,
                engine=engine,
            )
        except Exception:
            pass

        raise LLMError(f"LLM call failed: {e}") from e


def generate_embedding(text: str):
    """Generate an embedding vector for the given text using OpenAI embeddings.

    This uses OPENAI_EMBED_MODEL and requires OPENAI_API_KEY to be set, regardless of
    the primary chat provider.
    """
    if not text or not str(text).strip():
        raise ValueError("Text for embedding must be non-empty")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for embeddings")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.embeddings.create(model=OPENAI_EMBED_MODEL, input=[str(text).strip()])
    if not resp or not getattr(resp, "data", None):
        raise LLMError("Embedding response missing data")

    vector = getattr(resp.data[0], "embedding", None)
    if not vector:
        raise LLMError("Embedding vector missing in response")
    return list(vector)
