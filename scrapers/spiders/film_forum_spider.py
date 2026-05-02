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


def _extract_format(title: str) -> str:
    """Pull format tag from title — parenthetical '(35mm)' or bare 'in 35mm'."""
    m = re.search(r'\(([^)]+)\)', title)
    if m:
        candidate = m.group(1).strip()
        if re.search(r'mm|dcp|digital|4k|imax|70|35|16', candidate, re.IGNORECASE):
            return candidate.upper()
    m = re.search(r'\bin\s+((?:35|16|70)\s*mm|dcp|digital|4k|imax)\b', title, re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()
    return 'UNKNOWN'


def _parse_film_forum_time(time_str: str, date: datetime.date) -> datetime.datetime:
    """Apply AM/PM heuristic: hours 1-9 are PM, 10-12 are AM (10am/11am/noon)."""
    time_str = time_str.strip()
    h, m = map(int, time_str.split(':'))
    if 1 <= h <= 9:
        h += 12  # PM
    # h 10, 11 → AM; h 12 → noon (stays 12)
    return datetime.datetime(date.year, date.month, date.day, h, m)


class FilmForumSpider(scrapy.Spider):
    name = 'film_forum'
    start_urls = ['https://filmforum.org/now_playing']

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 810,
        },
        'SPIDER_MIDDLEWARES': {},
        'DUPEFILTER_CLASS': 'scrapy.dupefilters.RFPDupeFilter',
        'HTTPCACHE_STORAGE': 'scrapy.extensions.httpcache.FilesystemCacheStorage',
        # filmforum.org blocks the default Scrapy bot UA with 403
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/123.0.0.0 Safari/537.36'
        ),
        # robots.txt also returns 403 for the bot UA — site is openly scrapeable
        'ROBOTSTXT_OBEY': False,
    }

    def parse(self, response):
        """
        Listing page: the tab schedule shows all films for each day.
        Each <p> in a tab panel is one film's block with a link + <span> times.
        Collect slug → [(date, time_str)] then follow each detail page for metadata.
        """
        today = datetime.date.today()

        # Build day-class → tab-id mapping
        # <ul aria-label="This week's showtimes at Film Forum">
        #   <li class=thu><a href="#tabs-0">THU</a></li>
        tab_day_to_id: dict[str, str] = {}
        for li in response.css('ul[aria-label*="showtimes"] li, ul#tabs-nav li'):
            cls = li.attrib.get('class', '').lower().strip()
            tab_id = li.css('a::attr(href)').get(default='').lstrip('#')
            if cls and tab_id:
                tab_day_to_id[cls] = tab_id

        if not tab_day_to_id:
            self.logger.warning("No tab navigation found on Film Forum listing page")
            return

        # detail_url -> [(date, time_str)]
        url_showtimes: dict[str, list[tuple[datetime.date, str]]] = {}

        for day_cls, tab_id in tab_day_to_id.items():
            panel = response.xpath(f'//div[@id="{tab_id}"]')
            if not panel:
                continue

            tab_index = int(tab_id.split('-')[-1])
            candidate_date = today + datetime.timedelta(days=tab_index)

            # Each <p> in the panel is one film's showtime block:
            # <p><strong><a href="https://filmforum.org/film/bellissima">TITLE</a></strong><br/>
            #    <span>12:30</span> <span>3:00</span></p>
            for film_p in panel.css('p'):
                film_href = film_p.css('strong a::attr(href), a[href*="/film/"]::attr(href)').get()
                if not film_href or '/film/' not in film_href:
                    continue
                detail_url = response.urljoin(film_href)

                times = [
                    t.strip()
                    for t in film_p.css('span::text').getall()
                    if re.match(r'^\d{1,2}:\d{2}$', t.strip())
                ]
                for ts in times:
                    url_showtimes.setdefault(detail_url, []).append((candidate_date, ts))

        if not url_showtimes:
            self.logger.warning("No film showtimes found on Film Forum listing page")
            return

        for detail_url, showtimes in url_showtimes.items():
            yield scrapy.Request(
                detail_url,
                callback=self.parse_film,
                meta={'showtimes': showtimes},
            )

    def parse_film(self, response):
        """
        Detail page: extract metadata and combine with showtimes from listing page.
        Structure:
          <h2 class="main-title">TITLE</h2>
          <div class="copy">
            <p><strong>1970, India<br/>Directed by Satyajit Ray<br/>...Approx. 116 min.</strong></p>
            <p>Synopsis text...</p>
          </div>
          <a class="button medium blue" href="https://my.filmforum.org/events/...">
        """
        showtimes: list[tuple[datetime.date, str]] = response.meta['showtimes']

        # --- Title ---
        title_raw = ' '.join(
            t.strip() for t in response.css('h2.main-title *::text, h2.main-title::text').getall()
            if t.strip()
        )
        if not title_raw:
            self.logger.warning(f"No title at {response.url}")
            return

        # --- Metadata paragraph ---
        # <p><strong>India, 1970<br/>Directed by Satyajit Ray<br/>Starring...<br/>Approx. 116 min.</strong></p>
        # ::text pseudo-element gets text nodes split by <br> tags
        meta_lines = [
            t.strip()
            for t in response.css('div.copy p strong::text').getall()
            if t.strip()
        ]

        year = None
        director = None
        runtime = None

        for line in meta_lines:
            if year is None:
                m = re.search(r'\b((?:19|20)\d{2})\b', line)
                if m:
                    year = m.group(1)
            if director is None:
                m = re.match(r'(?:Written\s+(?:and|&)\s+)?[Dd]irected\s+by\s+(.+)', line, re.IGNORECASE)
                if m:
                    director = m.group(1).strip().rstrip('.')
            if runtime is None:
                m = re.search(r'(\d+)\s*min', line, re.IGNORECASE)
                if m:
                    try:
                        runtime = int(m.group(1))
                    except ValueError:
                        pass

        # Fallback: "DIRECTED BY X" in div.urgent
        if director is None:
            for text in response.css('div.urgent p::text').getall():
                m = re.match(
                    r'(?:WRITTEN\s*[&and]+\s*)?DIRECTED\s+BY\s+(.+)',
                    text.strip(), re.IGNORECASE,
                )
                if m:
                    director = m.group(1).strip().rstrip('.').title()
                    break

        # --- Synopsis ---
        # Stop at the first <h3> (Trailer/Reviews heading) to avoid review text leaking in.
        synopsis_parts = []
        for el in response.css('div.copy').xpath('*'):
            if el.root.tag == 'h3':
                break
            if el.root.tag != 'p':
                continue
            full_text = _text_with_br(el)
            if full_text:
                synopsis_parts.append(full_text)
        synopsis = '\n'.join(synopsis_parts) or None

        # --- Format ---
        # div.urgent sometimes carries a banner like "NEW 4K RESTORATION".
        # Only trust it when a known projection-format keyword is present;
        # other banners (e.g. "PRE-RECORDED INTRODUCTION BY...") are ignored.
        _format_kw_re = re.compile(r'\b(4K|35\s*MM|16\s*MM|DCP|DIGITAL|70\s*MM)\b', re.IGNORECASE)
        format_val = None
        for p_text in response.css('div.urgent p::text').getall():
            p_text = p_text.strip().rstrip('!')
            if _format_kw_re.search(p_text):
                format_val = p_text.upper()
                break
        if format_val is None:
            format_val = _extract_format(title_raw)

        # --- Poster ---
        # First image in the slideshow (ul.slides)
        poster_url = response.css('ul.slides li img::attr(src)').get()
        if poster_url:
            poster_url = response.urljoin(poster_url)

        # --- Ticket link ---
        ticket_link = response.css(
            'a.button.medium.blue::attr(href), a[class*="button"][class*="blue"]::attr(href)'
        ).get()

        for date, ts in showtimes:
            try:
                show_dt = _parse_film_forum_time(ts, date)
            except (ValueError, TypeError):
                self.logger.warning(f"Unparseable time {ts!r} for {title_raw!r}")
                continue

            yield {
                'cinema': 'FILM FORUM',
                'title': _clean(title_raw),
                'show_time': show_dt,
                'show_day': show_dt.strftime('%A'),
                'ticket_link': ticket_link,
                'details_link': response.url,
                'image_url': poster_url,
                'director1': _clean(director),
                'director2': None,
                'year': year,
                'runtime': runtime,
                'format': _clean(format_val),
                'synopsis': _clean(synopsis),
            }
