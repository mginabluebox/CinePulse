import os
import time
import json
import requests
from typing import Optional
from errors import LLMError

DEFAULT_OPENAI_TIMEOUT = 30
DEFAULT_OLLAMA_TIMEOUT = 30


def openai_generate(prompt: str, model: Optional[str] = None, max_tokens: int = 512, temperature: float = 0.7):
    """Call OpenAI Chat Completions API and return text content from the first choice."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1/chat/completions")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    resp = requests.post(base, headers=headers, json=payload, timeout=DEFAULT_OPENAI_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    # extract message content for chat completion
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        # fall back to other shapes
        try:
            return data["choices"][0].get("text") or json.dumps(data["choices"][0])
        except Exception:
            return json.dumps(data)


def ollama_generate(prompt: str, model: Optional[str] = None, max_tokens: int = 512, temperature: float = 0.7):
    """Call Ollama local HTTP API and return the response text (handles common response shapes)."""
    base = os.getenv("OLLAMA_BASE", "http://localhost:11434/api")
    model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    payload = {"model": model, "prompt": prompt, "max_tokens": max_tokens, "temperature": temperature, "stream": False}
    resp = requests.post(f"{base}/generate", json=payload, timeout=DEFAULT_OLLAMA_TIMEOUT)
    resp.raise_for_status()
    data = None
    try:
        data = resp.json()
    except Exception:
        return resp.text

    # common shapes
    if isinstance(data, dict):
        if "response" in data and isinstance(data["response"], str):
            return data["response"]
        if "output" in data and isinstance(data["output"], str):
            return data["output"]
        if "result" in data and isinstance(data["result"], str):
            return data["result"]
        if "choices" in data and isinstance(data["choices"], list) and data["choices"]:
            choice = data["choices"][0]
            return choice.get("text") or choice.get("content") or json.dumps(choice)
    return resp.text


def call_llm(prompt: str, provider: Optional[str] = None, **kw):
    """Dispatch to the configured LLM provider. Provider can be 'openai' or 'ollama'.

    Retries once on error with a short backoff.
    Returns the raw text content from the model.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).lower()
    last_err = None
    for attempt in range(2):
        try:
            if provider == "openai":
                return openai_generate(prompt, **kw)
            else:
                return ollama_generate(prompt, **kw)
        except Exception as e:
            last_err = e
            # small backoff then retry once
            time.sleep(1)
            continue
    # Wrap the last error in an LLMError for callers to handle specifically
    raise LLMError(f"LLM call failed after retries: {last_err}") from last_err
