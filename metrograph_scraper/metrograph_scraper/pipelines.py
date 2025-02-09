# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
from dotenv import load_dotenv
import os
import psycopg2

# class MetrographScraperPipeline:
#     def process_item(self, item, spider):
#         return item

load_dotenv()

class MetrographScraperPipeline:
    def open_spider(self, spider):
        
        # Read from environment variables
        dbname = os.getenv('DB_NAME')
        user = os.getenv('DB_USER')
        password = os.getenv('DB_PASSWORD')
        host = os.getenv('DB_HOST')

        # Connect to the PostgreSQL database
        self.conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host
        )
        self.cur = self.conn.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.conn.close()

    def process_item(self, item, spider):
        self.cur.execute("""
            INSERT INTO showtimes 
            (title, show_time, show_day, ticket_link, director1, director2, year, runtime, format, synopsis)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING;
        """, (
            item.get('title'),
            item.get('show_time'),  # Make sure this is in TIMESTAMP format
            item.get('show_day'),
            item.get('ticket_link'),
            item.get('director1'),
            item.get('director2'),
            item.get('year'),
            item.get('runtime'),  # This is now stored as an integer
            item.get('format'),
            item.get('synopsis')
        ))
        self.conn.commit()
        return item