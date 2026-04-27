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
from src.database.dedup_movies import (
    _normalize_whitespace,
    _scraped_title_normalized,
    _api_lookup_title,
    _strip_display_suffix,
)
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
from datetime import datetime, timezone

# Find .env in the root folder
load_dotenv(find_dotenv())


def _prepare_item(raw_title: str, cinema: str) -> dict:
    """Compute all title normalizations applied before any DB write.

    Both CinemaScraperPipeline and DryRunCollectorPipeline call this, so edits
    here are automatically exercised by --dry-run before touching the DB.
    """
    title = _normalize_whitespace(raw_title)
    clean_title = _strip_display_suffix(title)
    return {
        'title': title,
        'clean_title': clean_title,
        'dedup_key': _scraped_title_normalized(title, cinema),
        'api_lookup': _api_lookup_title(clean_title, cinema),
    }


class DryRunCollectorPipeline:
    """No-write pipeline for --dry-run. Collects items in class-level state shared
    across all spider instances; never touches the DB.

    Call DryRunCollectorPipeline.reset(n) before starting CrawlerProcess, then
    read DryRunCollectorPipeline.items after it finishes.
    """
    items: list[dict] = []
    _seen: dict[str, set] = {}
    _limit: int = 10

    @classmethod
    def reset(cls, limit: int = 10) -> None:
        cls.items = []
        cls._seen = {}
        cls._limit = limit

    def process_item(self, item, spider):
        cinema = item.get('cinema', 'UNKNOWN')
        norm = _prepare_item(item.get('title') or '', cinema)
        seen = DryRunCollectorPipeline._seen
        seen.setdefault(cinema, set())
        if norm['title'] not in seen[cinema]:
            if len(seen[cinema]) >= DryRunCollectorPipeline._limit:
                spider.crawler.engine.close_spider(spider, 'dry_run_limit')
                return item  # spider closing — discard overflow items
            seen[cinema].add(norm['title'])
        DryRunCollectorPipeline.items.append({
            **dict(item),
            'title': norm['title'],
            '_pipeline_clean_title': norm['clean_title'],
            '_pipeline_dedup_key': norm['dedup_key'],
            '_pipeline_api_lookup': norm['api_lookup'],
        })
        return item


class CinemaScraperPipeline:
    def __init__(self, test_mode=False):
        self.test_mode = test_mode

    @classmethod
    def from_crawler(cls, crawler):
        return cls(test_mode=crawler.settings.getbool('TEST_MODE', False))

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
            year = item.get('year')
            cinema = item.get('cinema') or 'UNKNOWN'
            if self.test_mode:
                cinema = f'TEST_{cinema}'

            norm = _prepare_item(item.get('title') or '', cinema)
            title = norm['title']
            clean_title = norm['clean_title']
            dedup_key = norm['dedup_key']
            api_lookup = norm['api_lookup']

            spider.logger.debug(f"Pipeline: updating item {title!r} in movies table")
            self.cur.execute("""
                UPDATE movies
                SET
                    title = %s,
                    year = %s,
                    updated_at = %s,
                    scraped_synopsis = %s,
                    scraped_director1 = %s,
                    scraped_cinema = %s,
                    scraped_image_url = %s,
                    scraped_details_link = %s,
                    scraped_title_normalized = %s
                WHERE lower(trim(title)) = %s
                  AND (year IS NOT DISTINCT FROM %s)
                RETURNING id;
            """, (
                clean_title,
                year,
                datetime.now(timezone.utc),
                item.get('synopsis'),
                item.get('director1'),
                cinema,
                item.get('image_url'),
                item.get('details_link'),
                api_lookup,
                dedup_key,
                year,
            ))

            row = self.cur.fetchone()
            if row:
                movie_id = row[0]
            else:
                spider.logger.debug(f"Pipeline: inserting item {title!r} into movies table")
                self.cur.execute("""
                    INSERT INTO movies (title, year, updated_at, scraped_synopsis, scraped_director1, scraped_cinema, scraped_image_url, scraped_details_link, scraped_title_normalized)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (
                    clean_title,
                    year,
                    datetime.now(timezone.utc),
                    item.get('synopsis'),
                    item.get('director1'),
                    cinema,
                    item.get('image_url'),
                    item.get('details_link'),
                    api_lookup,
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
                details_link,
                image_url,
                director1,
                director2,
                year,
                runtime,
                format,
                synopsis,
                cinema
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (movie_id, show_time, cinema, format)
            DO UPDATE SET
                crawled_at   = EXCLUDED.crawled_at,
                title        = EXCLUDED.title,
                year         = EXCLUDED.year,
                show_day     = EXCLUDED.show_day,
                ticket_link  = EXCLUDED.ticket_link,
                details_link = EXCLUDED.details_link,
                image_url    = EXCLUDED.image_url,
                director1    = EXCLUDED.director1,
                director2    = EXCLUDED.director2,
                runtime      = EXCLUDED.runtime,
                synopsis     = EXCLUDED.synopsis;
            """, (
                movie_id,
                title,
                datetime.now(timezone.utc),
                item.get('show_time'),
                item.get('show_day'),
                item.get('ticket_link'),
                item.get('details_link'),
                item.get('image_url'),
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