# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from src.database.setup_db import get_engine
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
from datetime import datetime, timezone

# Find .env in the root folder
load_dotenv(find_dotenv())

class MetrographScraperPipeline:
    def open_spider(self, spider):
        # Connect via SQLAlchemy engine to reuse env logic in setup_db.get_engine()
        engine = get_engine()
        # raw_connection() returns a DB-API (psycopg2) connection so existing cursor code still works
        self.conn = engine.raw_connection()
        self.cur = self.conn.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.conn.close()
    
    def process_item(self, item, spider):
        
        try:
            title = item.get('title')
            year = item.get('year')
            cinema = 'METROGRAPH'

            ## Update movies table
            # TODO: add embeddings field
            # First: try UPDATE existing entry in movies table
            spider.logger.debug(f"Pipeline: updating item {(item.get('title'))} in movies table")
            self.cur.execute("""
                UPDATE movies
                SET
                    title = %s,
                    year = %s,
                    updated_at = %s,
                    scraped_synopsis = %s,
                    scraped_director1 = %s,
                    scraped_cinema = %s
                WHERE lower(trim(title)) = lower(trim(%s))
                  AND (year IS NOT DISTINCT FROM %s)
                RETURNING id;
            """, (
                title,
                year,
                datetime.now(timezone.utc),
                item.get('synopsis'),
                item.get('director1'),
                cinema,
                title,
                year,
            ))

            row = self.cur.fetchone()
            if row:
                movie_id = row[0]
            else:
                # Then: INSERT a new entry
                spider.logger.debug(f"Pipeline: inserting item {(item.get('title'))} into movies table")
                self.cur.execute("""
                    INSERT INTO movies (title, year, updated_at, scraped_synopsis, scraped_director1, scraped_cinema)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (
                    title,
                    year,
                    datetime.now(timezone.utc),
                    item.get('synopsis'),
                    item.get('director1'),
                    'METROGRAPH'
                ))
                movie_id = self.cur.fetchone()[0]
    
            
            ## Update showtimes table
            spider.logger.debug(f"Pipeline: inserting/updating item {(item.get('title'))}, {(item.get('show_time'))} in showtimes table")
            self.cur.execute("""
            INSERT INTO showtimes (
                movie_id,
                title,
                crawled_at,
                show_time,
                show_day,
                ticket_link,
                director1,
                director2,
                year,
                runtime,
                format,
                synopsis,
                cinema
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (movie_id, show_time, cinema, format)
            DO UPDATE SET
                crawled_at  = EXCLUDED.crawled_at,
                title       = EXCLUDED.title,
                year        = EXCLUDED.year,
                show_day    = EXCLUDED.show_day,
                ticket_link = EXCLUDED.ticket_link,
                director1   = EXCLUDED.director1,
                director2   = EXCLUDED.director2,
                runtime     = EXCLUDED.runtime,
                synopsis    = EXCLUDED.synopsis;
            """, (
                movie_id,
                title,
                datetime.now(timezone.utc),
                item.get('show_time'),
                item.get('show_day'),
                item.get('ticket_link'),
                item.get('director1'),
                item.get('director2'),
                year,
                item.get('runtime'),
                item.get('format'),
                item.get('synopsis'),
                cinema,
            ))

            self.conn.commit()
        except psycopg2.Error as e:
            # Log original DB error and rollback so subsequent commands can run
            spider.logger.error(f"DB error inserting item {(item.get('title'))}: {e}")
            try:
                self.conn.rollback()
            except Exception as re:
                spider.logger.error(f"Rollback failed: {re}")
        return item