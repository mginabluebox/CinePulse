from sqlalchemy import func, text
from .setup_db import get_session
from .models import Showtime


def get_showtimes(interval_days: int = 14):
    """Fetch upcoming showtimes from the database using ORM.

    Args:
        interval_days: how many days into the future to include (default: 14).

    Returns:
        A list of dictionaries describing upcoming showtimes.
    """
    session = get_session()
    try:
        # Safely coerce to int and build a Postgres interval string
        try:
            days = int(interval_days)
        except Exception:
            days = 14

        interval_sql = text(f"interval '{days} days'")

        # Query the database for showtimes within the provided interval
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
            Showtime.show_time >= func.now(),
            Showtime.show_time < func.now() + interval_sql,
        ).order_by(Showtime.show_time.asc()).all()

        # Convert the result to a list of dictionaries for easier use in templates
        return [
            {
                "id": row.id,
                "title": row.title,
                "showdate": row.showdate,
                "showtime": row.showtime,
                "show_day": row.show_day,
                "ticket_link": row.ticket_link,
                "director": row.director1,
                "year": row.year,
                "runtime": row.runtime,
                "format": row.format,
                "synopsis": row.synopsis,
                "cinema": row.cinema,
            }
            for row in showtimes
        ]
    finally:
        session.close()


def get_showtimes_by_ids(ids):
    """Fetch showtime rows matching the given list of ids.

    Args:
        ids: iterable of integer ids

    Returns:
        List of dicts with the same shape as get_showtimes()
    """
    session = get_session()
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
                "ticket_link": row.ticket_link,
                "director": row.director1,
                "year": row.year,
                "runtime": row.runtime,
                "format": row.format,
                "synopsis": row.synopsis,
                "cinema": row.cinema,
            }
            for row in showtimes
        ]
    finally:
        session.close()