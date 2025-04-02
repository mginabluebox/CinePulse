# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import os
import psycopg2
from itemadapter import ItemAdapter
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
from datetime import datetime

# Find .env in the root folder
load_dotenv(find_dotenv())

class MetrographScraperPipeline:
    def open_spider(self, spider):
        
        # Read from environment variables
        dbname = os.getenv('DB_NAME')
        user = os.getenv('DB_USER')
        password = os.getenv('DB_PASSWORD')
        host = os.getenv('DB_HOST')
        port=os.getenv("DB_PORT")

        # Connect to the PostgreSQL database
        self.conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port
        )
        self.cur = self.conn.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.conn.close()

    def process_item(self, item, spider):
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
        return item