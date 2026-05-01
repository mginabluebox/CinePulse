import datetime
import re

import scrapy


def _clean(val):
    """Strip non-breaking spaces and leading/trailing whitespace from scraped text."""
    if not isinstance(val, str):
        return val
    return val.replace('\xa0', ' ').strip()


def _text_with_br(selector):
    """Extract text from a Scrapy selector, converting <br> tags to \\n."""
    def _walk(node):
        parts = []
        if node.text:
            parts.append(node.text)
        for child in node:
            tag = child.tag if isinstance(child.tag, str) else ''
            if tag.lower() == 'br':
                parts.append('\n')
            else:
                parts.append(_walk(child))
            if child.tail:
                parts.append(child.tail)
        return ''.join(parts)
    raw = _walk(selector.root)
    raw = re.sub(r'[ \t]+', ' ', raw)
    raw = re.sub(r' *\n *', '\n', raw)
    raw = re.sub(r'\n{3,}', '\n\n', raw)
    return raw.strip()


def _infer_year(month: int, day: int, today: datetime.date) -> int:
    """Pick the nearest upcoming year for a given month/day."""
    candidate = today.replace(month=month, day=day)
    if (today - candidate).days > 60:
        return today.year + 1
    return today.year


class IFCCenterSpider(scrapy.Spider):
    name = 'ifc_center'
    start_urls = ['https://www.ifccenter.com/']

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 810,
        },
        'SPIDER_MIDDLEWARES': {},
        'DUPEFILTER_CLASS': 'scrapy.dupefilters.RFPDupeFilter',
        'HTTPCACHE_STORAGE': 'scrapy.extensions.httpcache.FilesystemCacheStorage',
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/123.0.0.0 Safari/537.36'
        ),
        'ROBOTSTXT_OBEY': False,
    }

    def parse(self, response):
        today = datetime.date.today()
        # slug -> list of partial item dicts
        slug_items: dict[str, list[dict]] = {}
        slug_title: dict[str, str] = {}

        for day_div in response.css('div.daily-schedule'):
            date_text = day_div.css('h3::text').get(default='').strip()
            show_date = None
            try:
                dt = datetime.datetime.strptime(date_text, '%a %b %d')
                year = _infer_year(dt.month, dt.day, today)
                show_date = datetime.date(year, dt.month, dt.day)
            except ValueError:
                self.logger.warning(f"Cannot parse schedule date: {date_text!r}")
                continue

            for film_li in day_div.css('ul > li'):
                
                # get details_link
                film_href = film_li.css('a[href*="/films/"]::attr(href)').get()
                if not film_href:
                    continue
                film_url = response.urljoin(film_href)
                slug = film_href.rstrip('/').split('/')[-1]
                
                # get default title
                title = film_li.css('div.details h3 a::text, h3 a::text').get(default='').strip()
                if not title:
                    title = film_li.css('h3::text').get(default='').strip()
                
                if title:
                    slug_title.setdefault(slug, title)

                for time_a in film_li.css('ul.times li a'):
                    time_text = time_a.css('::text').get(default='').strip()
                    ticket_href = time_a.attrib.get('href', '')

                    try:
                        t = datetime.datetime.strptime(time_text, '%I:%M %p')
                        show_dt = datetime.datetime(
                            show_date.year, show_date.month, show_date.day,
                            t.hour, t.minute
                        )
                    except ValueError:
                        self.logger.warning(
                            f"Cannot parse showtime {time_text!r} for {title!r} on {show_date}"
                        )
                        continue

                    slug_items.setdefault(slug, []).append({
                        'show_time': show_dt,
                        'show_day': show_dt.strftime('%A'),
                        'ticket_link': ticket_href or None,
                    })

        for slug, items in slug_items.items():
            detail_url = f'https://www.ifccenter.com/films/{slug}/'
            yield scrapy.Request(
                detail_url,
                callback=self.parse_film,
                meta={
                    'slug': slug,
                    'items': items,
                    'title': slug_title.get(slug, ''),
                },
            )

    def parse_film(self, response):
        meta = response.meta
        partial_items: list[dict] = meta['items']
        listing_title: str = meta['title']

        # --- Title ---
        title = (
            response.css('h1.title::text, h1::text').get(default='').strip()
            or listing_title
        )

        # --- Metadata from <ul><li><strong>Label</strong> Value</li></ul> ---
        director = None
        year = datetime.date.today().year
        runtime = None
        format_val = 'UNKNOWN'

        for li in response.css('ul.film-details li'):
            label = li.css('strong::text').get('').strip()
            # Get text nodes that are direct children of <li> (outside <strong>)
            value = ' '.join(li.xpath('text()').getall()).strip()

            if label == 'Director' and value:
                director = value
            elif label == 'Year' and value:
                m = re.search(r'(\d{4})', value)
                if m:
                    year = int(m.group(1))
            elif label == 'Running Time' and value:
                m = re.search(r'(\d+)', value)
                if m:
                    runtime = int(m.group(1))
            elif label == 'Format' and value:
                format_val = value.upper()

        # --- Synopsis ---
        # <p> tags sit between the last <ul.schedule-list> and <ul.film-details>.
        # For films with no schedule-list, collect all <p> before film-details
        # (excluding the date-time header paragraph).
        if response.xpath('//ul[contains(@class,"schedule-list")]'):
            para_nodes = response.xpath(
                '//ul[contains(@class,"schedule-list")][last()]'
                '/following-sibling::p[following-sibling::ul[contains(@class,"film-details")]]'
            )
        else:
            para_nodes = response.xpath(
                '//p['
                'following-sibling::ul[contains(@class,"film-details")] and '
                'not(contains(@class,"date-time"))'
                ']'
            )
        paragraphs = [_text_with_br(p) for p in para_nodes if _text_with_br(p)]
        synopsis = '\n'.join(paragraphs) or None

        # --- Poster from detail page ---
        raw_poster = response.css('img.film-featured.wp-post-image::attr(src)').get()
        poster_url = response.urljoin(raw_poster) if raw_poster else None

        directors = [d.strip() for d in director.split(',')] if director else []

        for item in partial_items:
            yield {
                'cinema': 'IFC CENTER',
                'title': _clean(title),
                'show_time': item['show_time'],
                'show_day': item['show_day'],
                'ticket_link': item['ticket_link'],
                'details_link': response.url,
                'image_url': poster_url,
                'director1': _clean(directors[0]) if directors else None,
                'director2': _clean(directors[1]) if len(directors) > 1 else None,
                'year': year,
                'runtime': runtime,
                'format': _clean(format_val),
                'synopsis': _clean(synopsis),
            }
