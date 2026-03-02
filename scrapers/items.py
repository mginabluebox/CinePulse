# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class MetrographScraperItem(scrapy.Item):
    # define the fields for your item here like:
    title = scrapy.Field()
    show_time = scrapy.Field()
    show_day = scrapy.Field()
    ticket_link = scrapy.Field()
    image_url = scrapy.Field()
    director1 = scrapy.Field()
    director2 = scrapy.Field()
    year = scrapy.Field()
    runtime = scrapy.Field()
    format = scrapy.Field()
    synopsis = scrapy.Field()
