import datetime
import re

import requests
import scrapy
from lxml.html import fromstring


API_URL        = 'https://production-api.readingcinemas.com/films'
SETTINGS_URL   = 'https://production-api.readingcinemas.com/settings/6'
CLOUDFRONT_URL = 'https://d35zcch9f9it10.cloudfront.net'
IMAGE_PATH     = 'wpdata/images'
IMAGE_EXT      = '-oj.jpg'

CINEMAS = [
    ('nyc',         '0000000005', 'ANGELIKA NEW YORK'),
    ('villageeast', '0000000004', 'VILLAGE EAST BY ANGELIKA'),
    ('cinemas123',  '21',         'CINEMA 123 BY ANGELIKA'),
]

_FORMAT_RE = re.compile(
    r'^(?:35|16|70)\s*mm$|^dcp$|^digital$|^4k$|^imax$', re.IGNORECASE
)
_BORING_TYPES = {'standard', ''}


def _clean(val):
    if not isinstance(val, str):
        return val
    return val.replace('\xa0', ' ').strip()


def _strip_html(text: str) -> str | None:
    if not text:
        return None
    try:
        return re.sub(r'\s+', ' ', fromstring(text).text_content()).strip() or None
    except Exception:
        return re.sub(r'<[^>]+>', ' ', text).strip() or None


def _parse_title(raw: str) -> tuple[str, int | None, str | None]:
    """Return (title, year_or_None, format_or_None) parsed from the display name."""
    year = None
    m = re.search(r'\((\d{4})\)\s*$', raw)
    if m:
        year = int(m.group(1))

    format_val = None
    m = re.search(
        r'\bin\s+((?:35|16|70)\s*mm|dcp|digital|4k|imax)\b', raw, re.IGNORECASE
    )
    if m:
        format_val = m.group(1).strip().upper().replace(' ', '')

    return raw.strip(), year, format_val


def _classify_showtype(
    type_name: str, format_from_title: str | None
) -> tuple[str, str | None]:
    """Return (format, special_attribute_or_None) from a showtype string.

    showtype.type serves three roles in the API:
      - format indicator  ("35mm", "70mm")
      - generic screen    ("Standard", "Open Captions", "Jaffe Art Theatre")
      - special event     ("Q&A to follow the screening", "Introduction prior …")
    """
    t = type_name.strip()
    if _FORMAT_RE.match(t):
        return t.upper().replace(' ', ''), None
    if t.lower() in _BORING_TYPES:
        return format_from_title or 'UNKNOWN', None
    return format_from_title or 'UNKNOWN', t.upper() or None


def _parse_showtime_dt(dt_str: str) -> datetime.datetime | None:
    """Parse '2026-05-02T21:45:00-04' → naive local datetime (ET)."""
    try:
        normalized = re.sub(r'([+-]\d{2})$', r'\1:00', dt_str)
        aware = datetime.datetime.fromisoformat(normalized)
        return aware.replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


class AngelikaSpider(scrapy.Spider):
    name = 'angelika'

    custom_settings = {
        'DOWNLOAD_DELAY': 1,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': False,
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/123.0.0.0 Safari/537.36'
        ),
    }

    def start_requests(self):
        token = self._fetch_token()
        for slug, cinema_id, cinema_name in CINEMAS:
            url = (
                f'{API_URL}?brandId=US&countryId=6'
                f'&cinemaId={cinema_id}&status=getShows&flag=nowshowing'
            )
            yield scrapy.Request(
                url,
                headers={'Authorization': f'Bearer {token}'},
                meta={'cinema': cinema_name, 'cinema_slug': slug},
                callback=self.parse,
            )

    def _fetch_token(self) -> str:
        resp = requests.get(SETTINGS_URL, timeout=15)
        resp.raise_for_status()
        return resp.json()['data']['settings']['token']

    def parse(self, response):
        cinema      = response.meta['cinema']
        cinema_slug = response.meta['cinema_slug']

        body = response.json()
        if isinstance(body, list):
            films = body
        else:
            films = body.get('nowShowing', {}).get('data', {}).get('movies', [])
        for film in films:
            raw_name = film.get('name', '') or ''
            title, year, format_from_title = _parse_title(raw_name)

            dirs = [
                d.strip()
                for d in (film.get('director') or '').split(',')
                if d.strip()
            ]

            runtime = None
            try:
                runtime = int(film.get('length') or 0) or None
            except (ValueError, TypeError):
                pass

            synopsis     = _clean(_strip_html(film.get('synopsis') or ''))
            movie_poster = film.get('moviePoster') or ''
            image_url = (
                f'{CLOUDFRONT_URL}/{IMAGE_PATH}/{movie_poster}{IMAGE_EXT}'
                if movie_poster
                else film.get('poster_image') or film.get('film_image_original_size')
            )
            movie_slug   = film.get('movieSlug', '')
            details_link = (
                f'https://angelikafilmcenter.com/{cinema_slug}/movies/details/{movie_slug}'
            )

            for showdate in film.get('showdates', []):
                for showtype in showdate.get('showtypes', []):
                    type_name = showtype.get('type', '') or ''
                    fmt, special_attr = _classify_showtype(type_name, format_from_title)

                    for st in showtype.get('showtimes', []):
                        show_dt = _parse_showtime_dt(st.get('date_time', ''))
                        if not show_dt:
                            self.logger.warning(
                                f"Cannot parse datetime {st.get('date_time')!r} "
                                f"for {title!r}"
                            )
                            continue

                        soldout = st.get('soldout', False)
                        if soldout:
                            ticket_link = 'sold_out'
                        else:
                            ticket_link = f'{details_link}#showTime'

                        yield {
                            'cinema':            cinema,
                            'title':             _clean(title),
                            'show_time':         show_dt,
                            'show_day':          show_dt.strftime('%A'),
                            'ticket_link':       ticket_link,
                            'details_link':      details_link,
                            'image_url':         image_url,
                            'director1':         _clean(dirs[0]) if dirs else None,
                            'director2':         _clean(dirs[1]) if len(dirs) > 1 else None,
                            'year':              year,
                            'runtime':           runtime,
                            'format':            fmt,
                            'synopsis':          synopsis,
                            'special_attributes': special_attr,
                            'trailer_url':       film.get('youtube_id') or None,
                        }
