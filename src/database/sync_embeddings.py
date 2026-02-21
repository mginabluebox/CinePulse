"""Utilities to get pgvector embeddings for movies."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Iterable, List, Sequence

import hashlib

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Movie
from .setup_db import get_session


LOGGER = logging.getLogger("sync_embeddings")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

EMBEDDING_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# text-embedding-3-small outputs 1,536 dimensional vectors
EMBEDDING_DIM = 1536
DEFAULT_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", 16))


def _chunked(items: Sequence[Movie], chunk_size: int) -> Iterable[Sequence[Movie]]:
    for idx in range(0, len(items), chunk_size):
        yield items[idx: idx + chunk_size]

def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _build_embedding_input(movie: Movie) -> str:
    """Compose a deterministic text blob for embedding calls."""

    parts: List[str] = []
    if movie.title:
        parts.append(f"Title: {str(movie.title).strip()}")
    if movie.year:
        parts.append(f"Year: {movie.year}")
    if movie.scraped_director1:
        parts.append(f"Director: {movie.scraped_director1}")
    if movie.scraped_synopsis:
        parts.append(f"Synopsis: {str(movie.scraped_synopsis).strip()}")

    text = " | ".join(p for p in parts if p)
    
    return text


def _validate_env() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set to generate embeddings")

def _needs_embedding(movie: Movie) -> bool:
    text = _build_embedding_input(movie)
    if not text.strip():
        return False
    current_hash = _source_hash(text)
    return (
        movie.embedding is None
        or movie.embedding_model != EMBEDDING_MODEL
        or movie.embedding_source_hash != current_hash
    )

def _fetch_movies(session: Session, refresh_all: bool, limit: int | None) -> List[Movie]:
    stmt = select(Movie).order_by(Movie.embedded_at.desc())
    if not refresh_all:
        stmt = stmt.where(
            (Movie.embedding.is_(None)) |
            (Movie.embedding_model != EMBEDDING_MODEL)
        )
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def _create_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _generate_embeddings(client: OpenAI, payloads: Sequence[str]) -> List[List[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=list(payloads))
    vectors: List[List[float]] = []
    for record in response.data:
        vector = getattr(record, "embedding", None)
        if not vector:
            raise RuntimeError("OpenAI response missing embedding data")
        if len(vector) != EMBEDDING_DIM:
            raise RuntimeError(
                f"Expected embedding dimension {EMBEDDING_DIM}, got {len(vector)}"
            )
        vectors.append(vector)
    return vectors


def sync_embeddings(refresh_all: bool = False, limit: int | None = None,
                    batch_size: int = DEFAULT_BATCH_SIZE, sleep_s: float = 0.0,
                    dry_run: bool = False) -> None:
    _validate_env()

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    session = get_session()
    try:
        movies = _fetch_movies(session, refresh_all=refresh_all, limit=limit)
        if refresh_all:
            movies_to_embed = movies
        else:
            movies_to_embed = [m for m in movies if _needs_embedding(m)]

        total = len(movies_to_embed)
        if total == 0:
            LOGGER.info("No movies require embeddings")
            return

        LOGGER.info("Found %s movie(s) needing embeddings", total)
        if dry_run:
            for movie in movies_to_embed:
                LOGGER.info("DRY-RUN would embed id=%s title=%s", movie.id, movie.title)
            return

        client = _create_client()
        processed = 0

        for batch in _chunked(movies_to_embed, batch_size):

            inputs = [_build_embedding_input(movie) for movie in batch]
            filtered_movies: List[Movie] = []
            filtered_inputs: List[str] = []
            for movie, payload in zip(batch, inputs):
                normalized = (payload or "").strip()
                if not normalized:
                    LOGGER.info(
                        "Skipping movie id=%s title=%s due to empty embedding payload",
                        movie.id,
                        movie.title,
                    )
                    continue
                filtered_movies.append(movie)
                filtered_inputs.append(normalized)

            if not filtered_movies:
                LOGGER.info("Skipping batch: no valid embedding payloads")
                continue

            source_hashes = [_source_hash(text) for text in filtered_inputs]
            vectors = _generate_embeddings(client, filtered_inputs)

            for movie, vector, source_hash in zip(filtered_movies, vectors, source_hashes):
                movie.embedding = vector
                movie.embedding_model = EMBEDDING_MODEL
                movie.embedding_source_hash = source_hash
                movie.embedded_at = datetime.now(timezone.utc)

            session.commit()

            processed += len(filtered_movies)
            LOGGER.info("Embedded %s/%s movies", processed, total)
            if sleep_s:
                time.sleep(sleep_s)

    except Exception:
        session.rollback()
        LOGGER.exception("Embedding sync failed")
        raise
    finally:
        session.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate pgvector embeddings for movies")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of movies to process")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Number of movies per OpenAI embedding request")
    parser.add_argument("--refresh-all", action="store_true",
                        help="Regenerate embeddings even for movies that already have one")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Seconds to sleep between batches to respect rate limits")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would run")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    sync_embeddings(
        refresh_all=args.refresh_all,
        limit=args.limit,
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
