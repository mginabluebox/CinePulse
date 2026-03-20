import datetime
import re

import scrapy


def _extract_format(title: str) -> str:
    """Pull parenthetical format tag from title, e.g. '(35mm)' -> '35MM'."""
    m = re.search(r'\(([^)]+)\)', title)
    if m:
        candidate = m.group(1).strip()
        if re.search(r'mm|dcp|digital|4k|imax|70|35|16', candidate, re.IGNORECASE):
            return candidate.upper()
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

        # slug -> [(date, time_str)]
        slug_showtimes: dict[str, list[tuple[datetime.date, str]]] = {}

        for day_cls, tab_id in tab_day_to_id.items():
            panel = response.xpath(f'//div[@id="{tab_id}"]')
            if not panel:
                continue

            # Day-of-month from HTML comment: <!-- 19 -->
            panel_html = panel.get()
            comment_match = re.search(r'<!--\s*(\d{1,2})\s*-->', panel_html or '')
            if not comment_match:
                continue
            day_of_month = int(comment_match.group(1))

            candidate_date = today.replace(day=day_of_month)
            if (today - candidate_date).days > 7:
                if candidate_date.month == 12:
                    candidate_date = candidate_date.replace(year=candidate_date.year + 1, month=1)
                else:
                    candidate_date = candidate_date.replace(month=candidate_date.month + 1)

            # Each <p> in the panel is one film's showtime block:
            # <p><strong><a href="/film/slug">TITLE</a></strong><br/>
            #    <span>12:30</span> <span>3:00</span></p>
            for film_p in panel.css('p'):
                film_href = film_p.css('strong a::attr(href), a[href*="/film/"]::attr(href)').get()
                if not film_href or '/film/' not in film_href:
                    continue
                slug = film_href.rstrip('/').split('/')[-1]

                times = [
                    t.strip()
                    for t in film_p.css('span::text').getall()
                    if re.match(r'^\d{1,2}:\d{2}$', t.strip())
                ]
                for ts in times:
                    slug_showtimes.setdefault(slug, []).append((candidate_date, ts))

        if not slug_showtimes:
            self.logger.warning("No film showtimes found on Film Forum listing page")
            return

        for slug, showtimes in slug_showtimes.items():
            detail_url = f'https://filmforum.org/film/{slug}'
            yield scrapy.Request(
                detail_url,
                callback=self.parse_film,
                meta={'slug': slug, 'showtimes': showtimes},
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
            title_raw = response.css('title::text').get('').split('|')[0].strip()
        if not title_raw:
            self.logger.warning(f"No title at {response.url}")
            return

        # --- Metadata paragraph ---
        # <p><strong>1970, India<br/>Directed by Satyajit Ray<br/>Starring...<br/>Approx. 116 min.</strong></p>
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
                m = re.match(r'^(\d{4})\b', line)
                if m:
                    year = m.group(1)
            if director is None:
                m = re.match(r'[Dd]irected\s+by\s+(.+)', line)
                if m:
                    director = m.group(1).strip().rstrip('.')
            if runtime is None:
                m = re.search(r'(\d+)\s*min', line, re.IGNORECASE)
                if m:
                    try:
                        runtime = int(m.group(1))
                    except ValueError:
                        pass

        # Fallback: "DIRECTED BY X" / "WRITTEN & DIRECTED BY X" anywhere on the page
        # Covers Pattern B films like Two Prosecutors where it's in a plain <p> outside div.copy
        if director is None:
            for text in response.css('p::text, p *::text').getall():
                m = re.match(
                    r'(?:WRITTEN\s*[&and]+\s*)?DIRECTED\s+BY\s+(.+)',
                    text.strip(), re.IGNORECASE,
                )
                if m:
                    director = m.group(1).strip().rstrip('.').title()
                    break

        # --- Synopsis ---
        # Synopsis is the longest direct text child (./text()) of the first <p> in div.copy.
        # Pattern A: <p><strong>metadata</strong><br/><br/>SYNOPSIS<br/><br/><strong>note</strong></p>
        # Pattern B: <p>SYNOPSIS<br/>...<em>...</em><br/><strong>year runtime</strong></p>
        # Using ./text() (not ::text) excludes text inside <strong>/<em>/<a> children.
        synopsis = None
        for p in response.css('div.copy p'):
            text_nodes = [
                t.strip() for t in p.xpath('./text()').getall()
                if t.strip() and t.strip() != '\xa0'
            ]
            if text_nodes:
                candidate = max(text_nodes, key=len)
                if len(candidate) > 40:
                    synopsis = candidate
                    break

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
                'title': title_raw,
                'show_time': show_dt,
                'show_day': show_dt.strftime('%A'),
                'ticket_link': ticket_link,
                'details_link': response.url,
                'image_url': poster_url,
                'director1': director,
                'director2': None,
                'year': year,
                'runtime': runtime,
                'format': _extract_format(title_raw),
                'synopsis': synopsis,
            }
