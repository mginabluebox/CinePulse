"""
Tests for scrapers/spiders/film_forum_spider.py

Covers helper functions and the parse_film() detail-page parser for the
edge cases documented in AGENTS.md ("Scraper edge cases"). Each Case block
below pins the page shape of a real film that once broke the parser.
"""
import datetime

import pytest
from scrapy.http import HtmlResponse, Request
from scrapy.selector import Selector

from scrapers.spiders.film_forum_spider import (
    FilmForumSpider,
    _clean,
    _extract_format,
    _parse_film_forum_time,
    _text_with_br,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(html: str, url: str = 'https://filmforum.org/film/test',
                   meta: dict = None) -> HtmlResponse:
    request = Request(url=url, meta=meta or {})
    return HtmlResponse(url=url, body=html, encoding='utf-8', request=request)


def _parse_film(html: str, url: str = 'https://filmforum.org/film/test',
                showtimes=None) -> dict:
    if showtimes is None:
        showtimes = [(datetime.date(2026, 4, 20), '7:30')]
    response = _make_response(html, url, meta={'showtimes': showtimes})
    items = list(FilmForumSpider().parse_film(response))
    assert items, "parse_film yielded nothing"
    return items[0]


def _p_selector(html: str):
    """Return a Scrapy selector for the first <p> in the given HTML."""
    return Selector(text=html).css('p')[0]


# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------

class TestClean:
    def test_strips_nbsp(self):
        assert _clean('hello\xa0world') == 'hello world'

    def test_strips_whitespace(self):
        assert _clean('  hi  ') == 'hi'

    def test_nbsp_and_whitespace(self):
        assert _clean('\xa0 text \xa0') == 'text'

    def test_passthrough_none(self):
        assert _clean(None) is None

    def test_passthrough_int(self):
        assert _clean(42) == 42


# ---------------------------------------------------------------------------
# _extract_format
# ---------------------------------------------------------------------------

class TestExtractFormat:
    def test_35mm(self):
        assert _extract_format('Some Film (35mm)') == '35MM'

    def test_dcp(self):
        assert _extract_format('Some Film (DCP)') == 'DCP'

    def test_4k(self):
        assert _extract_format('Some Film (4K DCP)') == '4K DCP'

    def test_no_parens(self):
        assert _extract_format('Some Film') == 'UNKNOWN'

    def test_non_format_parens(self):
        assert _extract_format('Some Film (Restored)') == 'UNKNOWN'


# ---------------------------------------------------------------------------
# _parse_film_forum_time
# ---------------------------------------------------------------------------

class TestParseFilmForumTime:
    DATE = datetime.date(2026, 4, 20)

    def test_hour_1_to_9_is_pm(self):
        assert _parse_film_forum_time('7:30', self.DATE).hour == 19

    def test_hour_9_is_pm(self):
        assert _parse_film_forum_time('9:00', self.DATE).hour == 21

    def test_hour_10_is_am(self):
        assert _parse_film_forum_time('10:00', self.DATE).hour == 10

    def test_hour_11_is_am(self):
        assert _parse_film_forum_time('11:00', self.DATE).hour == 11

    def test_noon_stays_12(self):
        assert _parse_film_forum_time('12:00', self.DATE).hour == 12

    def test_correct_date(self):
        dt = _parse_film_forum_time('3:15', self.DATE)
        assert dt.date() == self.DATE
        assert dt.minute == 15


# ---------------------------------------------------------------------------
# _text_with_br
# ---------------------------------------------------------------------------

class TestTextWithBr:
    def test_br_becomes_newline(self):
        text = _text_with_br(_p_selector('<p>Line one<br/>Line two</p>'))
        assert text == 'Line one\nLine two'

    def test_nested_em_included(self):
        text = _text_with_br(_p_selector('<p><em>Start</em> of sentence.</p>'))
        assert text == 'Start of sentence.'


# ---------------------------------------------------------------------------
# parse_film — Case 1: Synopsis text inside child elements (reunion)
# ---------------------------------------------------------------------------

REUNION_HTML = """
<html><body>
  <h2 class="main-title">Reunion</h2>
  <div class="copy">
    <p><strong>U.K./West Germany/France, 1989<br/>Directed by Jerry Schatzberg<br/>
       Starring Jason Robards<br/>Approx. 110 min.</strong></p>
    <p><em>Jason Robards</em> stars as a New York Jewish lawyer who returns to Stuttgart.</p>
  </div>
</body></html>
"""

class TestCase1Reunion:
    def test_synopsis_includes_prose(self):
        item = _parse_film(REUNION_HTML)
        assert 'New York Jewish lawyer who returns to Stuttgart' in item['synopsis']

    def test_year(self):
        assert _parse_film(REUNION_HTML)['year'] == '1989'

    def test_director(self):
        assert _parse_film(REUNION_HTML)['director1'] == 'Jerry Schatzberg'

    def test_runtime(self):
        assert _parse_film(REUNION_HTML)['runtime'] == 110


# ---------------------------------------------------------------------------
# parse_film — Case 2: Reviews section must not leak into synopsis
# ---------------------------------------------------------------------------

LIVING_THE_LAND_HTML = """
<html><body>
  <h2 class="main-title">Living the Land</h2>
  <div class="copy">
    <p>WINNER, SILVER BEAR FOR BEST DIRECTOR, 2025 BERLIN INTERNATIONAL FILM FESTIVAL.
       An intimate portrait of farming life across several generations.</p>
    <h3 id="trailer">Trailer</h3>
    <div><!-- embed --></div>
    <h3>Reviews</h3>
    <p>"Elegiac...a wonder of ensemble creation." – Sheila O'Malley, RogerEbert.com</p>
    <p>"A quiet masterpiece." – Some Critic</p>
  </div>
</body></html>
"""

class TestCase2LivingTheLand:
    def test_review_quote_excluded(self):
        item = _parse_film(LIVING_THE_LAND_HTML)
        assert 'Elegiac' not in item['synopsis']
        assert 'quiet masterpiece' not in item['synopsis']

    def test_synopsis_prose_included(self):
        item = _parse_film(LIVING_THE_LAND_HTML)
        assert 'intimate portrait' in item['synopsis']


# ---------------------------------------------------------------------------
# parse_film — Case 3: Pattern B — metadata and synopsis share one <p>
# ---------------------------------------------------------------------------

DAYS_AND_NIGHTS_HTML = """
<html><body>
  <h2 class="main-title">Days and Nights in the Forest</h2>
  <div class="copy">
    <p>
      <strong>India, 1970<br/>Directed by Satyajit Ray<br/>
      Starring Soumitra Chatterjee<br/>Approx. 116 min.</strong><br/>
      <br/>
      Four young men leave Calcutta for a weekend forest retreat.
    </p>
  </div>
</body></html>
"""

MONTE_CARLO_HTML = """
<html><body>
  <h2 class="main-title">Monte Carlo: The Lubitsch Touch</h2>
  <div class="copy">
    <p>
      <strong>U.S.A., 1930<br/>Directed by Ernst Lubitsch<br/>Approx. 90 min.</strong><br/>
      <br/>
      On the run from her wedding, a countess boards a train to Monte Carlo.
    </p>
  </div>
</body></html>
"""

class TestCase3PatternB:
    def test_days_and_nights_synopsis_includes_prose(self):
        item = _parse_film(DAYS_AND_NIGHTS_HTML)
        assert 'Four young men leave Calcutta' in item['synopsis']

    def test_days_and_nights_year(self):
        assert _parse_film(DAYS_AND_NIGHTS_HTML)['year'] == '1970'

    def test_days_and_nights_director(self):
        assert _parse_film(DAYS_AND_NIGHTS_HTML)['director1'] == 'Satyajit Ray'

    def test_monte_carlo_synopsis_includes_prose(self):
        item = _parse_film(MONTE_CARLO_HTML)
        assert 'On the run from her wedding' in item['synopsis']

    def test_monte_carlo_year(self):
        assert _parse_film(MONTE_CARLO_HTML)['year'] == '1930'


# ---------------------------------------------------------------------------
# parse_film — Case 4: Year extraction with "Country, Year" metadata format
# ---------------------------------------------------------------------------

COUNTRY_YEAR_HTML = """
<html><body>
  <h2 class="main-title">Test Film</h2>
  <div class="copy">
    <p><strong>U.K./West Germany/France, 1989<br/>Directed by Someone<br/>
       Approx. 100 min.</strong></p>
    <p>A long synopsis paragraph for this test film that exceeds the minimum length filter.</p>
  </div>
</body></html>
"""

YEAR_FIRST_HTML = """
<html><body>
  <h2 class="main-title">Test Film</h2>
  <div class="copy">
    <p><strong>1975, France<br/>Directed by Someone<br/>Approx. 100 min.</strong></p>
    <p>A long synopsis paragraph for this test film that exceeds the minimum length filter.</p>
  </div>
</body></html>
"""

class TestCase4YearExtraction:
    def test_country_then_year(self):
        assert _parse_film(COUNTRY_YEAR_HTML)['year'] == '1989'

    def test_year_then_country(self):
        assert _parse_film(YEAR_FIRST_HTML)['year'] == '1975'
