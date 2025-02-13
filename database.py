import psycopg2
import os
from dotenv import load_dotenv,find_dotenv

load_dotenv(find_dotenv())  # Load environment variables

def get_showtimes():

    """Fetch upcoming showtimes from the database."""

    # Read from environment variables
    dbname = os.getenv('DB_NAME')
    user = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    host = os.getenv('DB_HOST')
    port=os.getenv("DB_PORT")

    # Connect to the PostgreSQL database
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port
    )
    
    cur = conn.cursor()
    cur.execute("""
        SELECT 
                title, 
                to_char(show_time, 'YYYY-MM-DD') as showdate,
                to_char(show_time, 'HH12:MI AM') as showtime,
                show_day, 
                ticket_link, 
                director1, 
                year, 
                runtime, 
                coalesce(format,'-'), 
                synopsis, 
                cinema
        FROM showtimes
        WHERE show_time >= NOW()::timestamp
        AND show_time < NOW()::timestamp + INTERVAL '2 weeks'
        ORDER BY show_time ASC
    """)
    
    showtimes = cur.fetchall()
    cur.close()
    conn.close()
    
    return showtimes