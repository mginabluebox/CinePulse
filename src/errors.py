class LLMError(Exception):
    """Raised when the LLM provider (OpenAI/Ollama) fails."""
    pass


class DBError(Exception):
    """Raised for database-related failures in showtime fetching or lookups."""
    pass


class ParseError(Exception):
    """Raised when parsing model output fails or returns unexpected data."""
    pass
