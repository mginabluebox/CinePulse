import re

import scrapy
from datetime import datetime


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


class MetrographSpider(scrapy.Spider):
    name = 'metrograph'
    start_urls = ['https://metrograph.com/film/']

    def parse(self, response):
        for block in response.css('div.col-sm-12.homepage-in-theater-movie'):
            ### MOVIE-LEVEL INFO
            title = block.css('h3.movie_title a::text').get(default='').strip()
            detail_href = block.css('h3.movie_title a::attr(href)').get()
            image_url = block.css('img::attr(src)').get()

            # the last 2 h5s are always director, year / runtime / format
            descript = block.css('h5::text').getall()

            try:
                directors = [x.strip() for x in descript[-2].replace('Director:', '').split(',')]
                director1 = directors[0]
                director2 = None if len(directors) == 1 else directors[1]
            except Exception:
                director1 = None
                director2 = None

            try:
                year, runtime, format = descript[-1].split('/')
                year, runtime, format = year.strip(), runtime.strip(), format.strip()
            except Exception:
                try:
                    year, runtime = descript[-1].split('/')
                    year, runtime = year.strip(), runtime.strip()
                    format = 'UNKNOWN'
                except Exception:
                    year = runtime = None
                    format = 'UNKNOWN'

            try:
                runtime = int(runtime.replace('min', '').strip())
            except Exception:
                runtime = None

            ### SHOWTIME-LEVEL INFO
            showtimes = []
            showtimes_block = block.css('div.showtimes')
            headings = showtimes_block.css('h5.sr-only, h6')
            days = showtimes_block.css('div.film_day')
            for heading, day_div in zip(headings, days):
                date_text = heading.xpath('normalize-space(text())').get()
                day_number = heading.css('span.day-number::text').get()
                time_el = day_div.css('a')
                time_text = time_el.xpath('normalize-space(text())').get()

                if not time_text:
                    self.logger.warning(
                        f"Skipping showtime (no time) for title={title!r} "
                        f"date={date_text!r} day_number={day_number!r}"
                    )
                    continue
                time_text = time_text.strip()

                candidates = []
                if date_text:
                    parts = date_text.split()
                    month_part = parts[1] if len(parts) > 1 else parts[0]
                    if day_number:
                        candidates.append(f"{month_part} {day_number} {time_text}")
                        candidates.append(f"{parts[0]} {month_part} {day_number} {time_text}")
                    else:
                        candidates.append(f"{date_text} {time_text}")

                date_formats = [
                    "%b %d %I:%M%p",
                    "%B %d %I:%M%p",
                    "%a %b %d %I:%M%p",
                    "%A %B %d %I:%M%p",
                    "%b %d %I:%M %p",
                    "%B %d %I:%M %p",
                    "%a %b %d %I:%M %p",
                    "%A %B %d %I:%M %p",
                ]

                parsed_dt = None
                for cand in candidates:
                    for fmt in date_formats:
                        try:
                            parsed_dt = datetime.strptime(cand, fmt)
                            break
                        except Exception:
                            continue
                    if parsed_dt:
                        break

                if not parsed_dt:
                    self.logger.error(
                        f"Failed to parse date/time for title={title!r}: "
                        f"date_text={date_text!r} day_number={day_number!r} time={time_text!r}"
                    )
                    continue

                today = datetime.today()
                current_year = today.year
                if parsed_dt.month < today.month:
                    current_year += 1
                timestamp = parsed_dt.replace(year=current_year)

                try:
                    show_day = timestamp.strftime('%A')
                except Exception:
                    show_day = None

                ticket_link = 'sold_out'
                title_attr = day_div.css('a::attr(title)').get()
                href_attr = day_div.css('a::attr(href)').get()
                if title_attr and 'Buy Tickets' in title_attr and href_attr:
                    ticket_link = href_attr

                showtimes.append({
                    'show_time': timestamp,
                    'show_day': show_day,
                    'ticket_link': ticket_link,
                })

            if not showtimes or not detail_href:
                continue

            yield scrapy.Request(
                response.urljoin(detail_href),
                callback=self.parse_film,
                meta={
                    'showtimes': showtimes,
                    'title': title,
                    'image_url': image_url,
                    'director1': director1,
                    'director2': director2,
                    'year': year,
                    'runtime': runtime,
                    'format': format,
                },
            )

    def parse_film(self, response):
        meta = response.meta
        showtimes = meta['showtimes']

        # Full synopsis from detail page
        synopsis = None
        for selector in (
            'div.film-synopsis p',
            'div.synopsis p',
            '.film-body p',
            '.description p',
            'div.film-info p',
            'article p',
        ):
            for p in response.css(selector):
                text = _text_with_br(p)
                if len(text) > 60:
                    synopsis = text
                    break
            if synopsis:
                break
        for st in showtimes:
            yield {
                'cinema': 'METROGRAPH',
                'title': _clean(meta['title']),
                'show_time': st['show_time'],
                'show_day': st['show_day'],
                'ticket_link': st['ticket_link'],
                'details_link': response.url,
                'image_url': meta['image_url'],
                'director1': _clean(meta['director1']),
                'director2': _clean(meta['director2']),
                'year': meta['year'],
                'runtime': meta['runtime'],
                'format': _clean(meta['format']),
                'synopsis': _clean(synopsis),
            }
