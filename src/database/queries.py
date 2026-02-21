from sqlalchemy import func, text
from .setup_db import get_session
from .models import Showtime, Movie
from typing import Iterable, Optional


def get_movie_embeddings_by_id(
        movie_ids: Iterable[int],
        engine=None
        ):
    """Fetch movie embeddings based on movie_ids.

    Args:
        movie_ids: iterable of integer movie IDs.
        engine: optional SQLAlchemy engine to use.

    Returns:
        A dictionary mapping movie_id to its embedding vector.
    """
    # TODO


def get_showtimes(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        interval_days: Optional[int] = None, engine=None
        ):
    """Fetch upcoming showtimes from the database using ORM.

    Args:
        start_date: start date as a string or SQL expression (e.g., func.now()).
        end_date: end date as a string or SQL expression.
        interval_days: how many days into the future to include (default: 14).
        engine: optional SQLAlchemy engine to use.

    Returns:
        A list of dictionaries describing upcoming showtimes.
    """
    session = get_session(engine)

    if interval_days is not None:
        if start_date is not None or end_date is not None:
            raise ValueError("If interval_days is provided, start_date and end_date must be None")
        start_date = func.now()
        end_date = func.now() + text(f"interval '{int(interval_days)} days'")
    else:
        if start_date is None or end_date is None:
            raise ValueError("Either both start_date and end_date or interval_days must be provided")

    try:
        # TODO: add movie_id as a field to fetch
        showtimes = session.query(
            Showtime.id,
            Showtime.title,
            func.to_char(Showtime.show_time, 'YYYY-MM-DD').label('showdate'),
            func.to_char(Showtime.show_time, 'HH12:MI AM').label('showtime'),
            Showtime.show_day,
            Showtime.ticket_link,
            Showtime.director1,
            Showtime.year,
            Showtime.runtime,
            func.coalesce(Showtime.format, '-').label('format'),
            Showtime.synopsis,
            Showtime.cinema,
        ).filter(
            Showtime.show_time >= start_date,
            Showtime.show_time < end_date,
        ).order_by(Showtime.show_time.asc()).all()

        # Convert the result to a list of dictionaries for easier use in templates
        return [
            {
                "id": row.id,
                "title": row.title,

                "showdate": row.showdate,
                "showtime": row.showtime,
                "show_day": row.show_day,

                "director": row.director1,
                "year": row.year,
                "runtime": row.runtime,
                "format": row.format,
                "synopsis": row.synopsis,

                "cinema": row.cinema,
                "ticket_link": row.ticket_link,
            }
            for row in showtimes
        ]
    except Exception as exc:
        from errors import DBError
        raise DBError("Failed to fetch showtimes") from exc
    finally:
        session.close()


def get_showtimes_by_ids(ids: Iterable[int], engine=None):
    """Fetch showtime rows matching the given list of ids.

    Args:
        ids: iterable of integer ids

    Returns:
        List of dicts with the same shape as get_showtimes()
    """
    session = get_session(engine)
    try:
        if not ids:
            return []

        # ensure ids are ints
        try:
            ids_list = [int(i) for i in ids]
        except Exception:
            # fallback: try to coerce strings
            ids_list = []
            for i in ids:
                try:
                    ids_list.append(int(str(i).strip()))
                except Exception:
                    continue

        showtimes = session.query(
            Showtime.id,
            Showtime.title,
            func.to_char(Showtime.show_time, 'YYYY-MM-DD').label('showdate'),
            func.to_char(Showtime.show_time, 'HH12:MI AM').label('showtime'),
            Showtime.show_day,
            Showtime.ticket_link,
            Showtime.director1,
            Showtime.year,
            Showtime.runtime,
            func.coalesce(Showtime.format, '-').label('format'),
            Showtime.synopsis,
            Showtime.cinema,
        ).filter(Showtime.id.in_(ids_list)).order_by(Showtime.show_time.asc()).all()

        return [
            {
                "id": row.id,
                "title": row.title,

                "showdate": row.showdate,
                "showtime": row.showtime,
                "show_day": row.show_day,

                "director": row.director1,
                "year": row.year,
                "runtime": row.runtime,
                "format": row.format,
                "synopsis": row.synopsis,

                "cinema": row.cinema,
                "ticket_link": row.ticket_link,
            }
            for row in showtimes
        ]
    except Exception as exc:
        from errors import DBError
        raise DBError("Failed to fetch showtimes by ids") from exc
    finally:
        session.close()


def insert_recommendation_log(queried_at, api_name: str, model_name: str, prompt_num_token: int, prompt: str, response: str, error_code: int = 0, engine=None):
    """Insert a recommendation log row into recommendation_logs table.

    Params are straightforward; `queried_at` should be a datetime or SQL expression like func.now().
    This function is defensive and will raise DBError on failure.
    """
    session = get_session(engine)
    try:
        # Use a parameterized insert to avoid issues with quoting/size.
        # If queried_at is None or 'now()', embed SQL now() so the DB sets the timestamp.
        if queried_at is None or (isinstance(queried_at, str) and queried_at == "now()"):
            stmt = text(
                "INSERT INTO recommendation_logs (queried_at, api_name, model_name, prompt_num_token, prompt, response, error_code) "
                "VALUES (now(), :api_name, :model_name, :prompt_num_token, :prompt, :response, :error_code)"
            )
            params = {
                "api_name": api_name,
                "model_name": model_name,
                "prompt_num_token": prompt_num_token,
                "prompt": prompt,
                "response": response,
                "error_code": error_code,
            }
            session.execute(stmt, params)
        else:
            stmt = text(
                "INSERT INTO recommendation_logs (queried_at, api_name, model_name, prompt_num_token, prompt, response, error_code) "
                "VALUES (:queried_at, :api_name, :model_name, :prompt_num_token, :prompt, :response, :error_code)"
            )
            session.execute(
                stmt,
                {
                    "queried_at": queried_at,
                    "api_name": api_name,
                    "model_name": model_name,
                    "prompt_num_token": prompt_num_token,
                    "prompt": prompt,
                    "response": response,
                    "error_code": error_code,
                },
            )
        session.commit()
    except Exception as exc:
        # Import DBError lazily to avoid top-level cycles
        from errors import DBError

        session.rollback()
        raise DBError("Failed to insert recommendation log") from exc
    finally:
        session.close()
