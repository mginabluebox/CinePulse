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
from src.database.title_normalization import (
    _normalize_whitespace,
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
    _closed: set[str] = set()

    @classmethod
    def reset(cls, limit: int = 10) -> None:
        cls.items = []
        cls._seen = {}
        cls._limit = limit
        cls._closed = set()

    @classmethod
    def _is_full(cls, cinema: str) -> bool:
        return len(cls._seen.get(cinema, ())) >= cls._limit

    def process_item(self, item, spider):
        cinema = item.get('cinema', 'UNKNOWN')
        norm = _prepare_item(item.get('title') or '', cinema)
        seen = DryRunCollectorPipeline._seen
        seen.setdefault(cinema, set())

        new_title = norm['title'] not in seen[cinema]
        if new_title and DryRunCollectorPipeline._is_full(cinema):
            # Quota reached for this cinema. A spider may serve several cinemas
            # (Angelika fans out to one request per venue), so only close once every
            # cinema it declares is full — otherwise the first venue to fill would
            # cancel the others' in-flight requests and silently truncate them.
            self._maybe_close(spider)
            return item  # discard overflow items
        if new_title:
            seen[cinema].add(norm['title'])

        DryRunCollectorPipeline.items.append({
            **dict(item),
            'title': norm['title'],
            '_pipeline_clean_title': norm['clean_title'],
            '_pipeline_api_lookup': norm['api_lookup'],
        })
        return item

    def _maybe_close(self, spider) -> None:
        if spider.name in DryRunCollectorPipeline._closed:
            return  # already asked this spider to stop
        # Spiders declare their venues via `cinemas`; fall back to the one in hand.
        expected = getattr(spider, 'cinemas', None) or [
            c for c in DryRunCollectorPipeline._seen
        ]
        if not all(DryRunCollectorPipeline._is_full(c) for c in expected):
            return
        DryRunCollectorPipeline._closed.add(spider.name)
        spider.crawler.engine.close_spider(spider, 'dry_run_limit')


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
        # Marks the start of this crawl. Rows re-written during the run get a later
        # crawled_at (see process_item), so anything still older than this was not
        # touched by the current crawl and is a candidate for sweeping.
        self.run_started_at = datetime.now(timezone.utc)
        # Cinemas with at least one successful write this run — only these are swept,
        # so a cinema that failed to scrape entirely never has its rows deleted.
        self.written_cinemas: set[str] = set()

    def close_spider(self, spider):
        try:
            self._sweep_stale_showtimes(spider)
        finally:
            self.cur.close()
            self.conn.close()

    def _sweep_stale_showtimes(self, spider):
        """Delete future showtimes this crawl did not re-write.

        A change to any part of the ON CONFLICT key (show_time, format) or to the
        title/year that resolves movie_id makes the upsert insert a fresh row
        instead of updating the existing one, orphaning the stale row. Re-written
        rows get crawled_at >= run_started_at; untouched future rows keep an older
        crawled_at and are pruned here. Past showtimes are left as history.
        """
        for cinema in sorted(self.written_cinemas):
            try:
                self.cur.execute("""
                    DELETE FROM showtimes
                    WHERE cinema = %s
                      AND crawled_at < %s
                      AND show_time > now()
                """, (cinema, self.run_started_at))
                deleted = self.cur.rowcount
                self.conn.commit()
                if deleted:
                    spider.logger.info(
                        f"Swept {deleted} stale future showtime(s) for {cinema!r}"
                    )
            except psycopg2.Error as e:
                spider.logger.error(f"Sweep failed for {cinema!r}: {e}")
                try:
                    self.conn.rollback()
                except Exception as re:
                    spider.logger.error(f"Sweep rollback failed: {re}")
    
    def process_item(self, item, spider):
        
        try:
            year = item.get('year')
            cinema = item.get('cinema') or 'UNKNOWN'
            if self.test_mode:
                cinema = f'TEST_{cinema}'

            norm = _prepare_item(item.get('title') or '', cinema)
            title = norm['title']
            clean_title = norm['clean_title']
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
                WHERE lower(trim(title)) = lower(trim(%s))
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
                clean_title,
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
                cinema,
                special_attributes,
                trailer_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (movie_id, show_time, cinema, format)
            DO UPDATE SET
                crawled_at         = EXCLUDED.crawled_at,
                title              = EXCLUDED.title,
                year               = EXCLUDED.year,
                show_day           = EXCLUDED.show_day,
                ticket_link        = EXCLUDED.ticket_link,
                details_link       = EXCLUDED.details_link,
                image_url          = EXCLUDED.image_url,
                director1          = EXCLUDED.director1,
                director2          = EXCLUDED.director2,
                runtime            = EXCLUDED.runtime,
                synopsis           = EXCLUDED.synopsis,
                special_attributes = EXCLUDED.special_attributes,
                trailer_url        = EXCLUDED.trailer_url;
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
                item.get('special_attributes'),
                item.get('trailer_url'),
            ))

            self.conn.commit()
            # Only cinemas with a committed write are eligible for the close_spider
            # sweep, so a failed scrape never deletes an otherwise-untouched cinema.
            self.written_cinemas.add(cinema)
        except psycopg2.Error as e:
            # Log original DB error and rollback so subsequent commands can run
            spider.logger.error(f"DB error inserting item {(item.get('title'))}: {e}")
            try:
                self.conn.rollback()
            except Exception as re:
                spider.logger.error(f"Rollback failed: {re}")
        return item