# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import os
import psycopg2
try:
    from database.setup_db import get_engine
except Exception:
    from src.database.setup_db import get_engine
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
from datetime import datetime

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
        spider.logger.debug(f"Pipeline: inserting item {(item.get('title'), item.get('show_time'))}")
        try:
            self.cur.execute("""
                INSERT INTO showtimes 
                (title, crawled_at, show_time, show_day, ticket_link, director1, director2, year, runtime, format, synopsis, cinema)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING;
            """, (
                item.get('title'),
                datetime.now(),
                item.get('show_time'),
                item.get('show_day'),
                item.get('ticket_link'),
                item.get('director1'),
                item.get('director2'),
                item.get('year'),
                item.get('runtime'),
                item.get('format'),
                item.get('synopsis'),
                'METROGRAPH'
            ))
            self.conn.commit()
        except psycopg2.Error as e:
            # Log original DB error and rollback so subsequent commands can run
            spider.logger.error(f"DB error inserting item {(item.get('title'), item.get('show_time'))}: {e}")
            try:
                self.conn.rollback()
            except Exception as re:
                spider.logger.error(f"Rollback failed: {re}")
        return item