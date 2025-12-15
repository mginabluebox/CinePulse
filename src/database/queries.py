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