import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv, find_dotenv
from pathlib import Path

# Find .env in the root folder
load_dotenv(find_dotenv())

def create_table():
    """Connects to PostgreSQL and creates the showtimes table if it doesn't exist."""
    try:
        # Read from environment variables
        dbname = os.getenv('DB_NAME')
        user = os.getenv('DB_USER')
        password = os.getenv('DB_PASSWORD')
        host = os.getenv('DB_HOST')

        # Connect to the PostgreSQL database
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host
        )
        cur = conn.cursor()

        # Define the table creation query
        create_table_query = """
        DROP TABLE IF EXISTS showtimes;
        CREATE TABLE showtimes (
            id SERIAL PRIMARY KEY,
            crawled_at TIMESTAMP NOT NULL,
            title VARCHAR(255) NOT NULL,
            show_time TIMESTAMP NOT NULL,
            show_day VARCHAR(20) NOT NULL,
            ticket_link TEXT,
            director1 VARCHAR(255),
            director2 VARCHAR(255),
            year INTEGER,
            runtime INTEGER,
            format VARCHAR(50),
            synopsis TEXT,
            cinema TEXT
        );
        """

        # Execute the query
        cur.execute(create_table_query)
        conn.commit()

        print("Table 'showtimes' is set up successfully.")

        # Close the connection
        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error setting up the database: {e}")

if __name__ == "__main__":
    create_table()