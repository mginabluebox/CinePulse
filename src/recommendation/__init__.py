"""Lightweight recommendation package initializer.

Avoid importing heavy submodules at package import time to prevent
potential circular imports (the app should import specific symbols
from submodules, e.g. ``from recommendation.core import recommend_movies``).

This file exposes only package metadata.
"""

__all__ = ["recommendation"]
__version__ = "0.1.0"
