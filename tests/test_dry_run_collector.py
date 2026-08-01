"""Unit tests for DryRunCollectorPipeline (the --dry-run collector).

No network or DB: items are plain dicts and the spider/engine is mocked, matching the
"mock engines/cursors" convention in AGENTS.md.
"""
from unittest.mock import MagicMock

import pytest

from scrapers.pipelines import DryRunCollectorPipeline


class FakeSpider:
    """Stands in for a Scrapy spider, recording close_spider calls."""

    def __init__(self, name, cinemas=None):
        self.name = name
        if cinemas is not None:
            self.cinemas = cinemas
        self.closed = []
        self.crawler = MagicMock()
        self.crawler.engine.close_spider = lambda sp, reason: sp.closed.append(reason)


@pytest.fixture
def collector():
    """A reset collector at limit 3, plus a helper to feed showtime items."""
    DryRunCollectorPipeline.reset(3)
    pipe = DryRunCollectorPipeline()

    def feed(spider, cinema, title, n=1):
        for _ in range(n):
            pipe.process_item({'cinema': cinema, 'title': title}, spider)

    return feed


def _titles(cinema):
    return {i['title'] for i in DryRunCollectorPipeline.items if i['cinema'] == cinema}


def test_collects_up_to_limit_then_stops(collector):
    spider = FakeSpider('film_forum', ['FILM FORUM'])
    for i in range(6):
        collector(spider, 'FILM FORUM', f'Film {i}')

    assert _titles('FILM FORUM') == {'Film 0', 'Film 1', 'Film 2'}


def test_extra_showtimes_for_kept_movie_are_collected(collector):
    """The limit caps distinct movies, not showtimes — a kept film keeps accruing rows."""
    spider = FakeSpider('film_forum', ['FILM FORUM'])
    collector(spider, 'FILM FORUM', 'Film A', n=5)

    rows = [i for i in DryRunCollectorPipeline.items if i['title'] == 'Film A']
    assert len(rows) == 5


def test_multi_cinema_spider_not_closed_until_all_venues_full(collector):
    """Regression: the first venue to fill must not cancel the others' requests."""
    venues = ['ANGELIKA NEW YORK', 'VILLAGE EAST BY ANGELIKA', 'CINEMA 123 BY ANGELIKA']
    spider = FakeSpider('angelika', venues)

    # First venue fills and overflows.
    for i in range(5):
        collector(spider, venues[0], f'NY Film {i}')
    assert spider.closed == [], "spider closed while two venues were still empty"

    # Second venue fills; still one to go.
    for i in range(5):
        collector(spider, venues[1], f'VE Film {i}')
    assert spider.closed == []

    # Last venue fills — now the spider may stop.
    for i in range(5):
        collector(spider, venues[2], f'C123 Film {i}')
    assert spider.closed == ['dry_run_limit']

    for v in venues:
        assert len(_titles(v)) == 3


def test_single_cinema_spider_closes_once_full(collector):
    spider = FakeSpider('metrograph', ['METROGRAPH'])
    for i in range(5):
        collector(spider, 'METROGRAPH', f'Film {i}')

    assert spider.closed == ['dry_run_limit']


def test_close_is_requested_only_once(collector):
    """Every overflow item used to re-trigger close_spider."""
    spider = FakeSpider('metrograph', ['METROGRAPH'])
    for i in range(20):
        collector(spider, 'METROGRAPH', f'Film {i}')

    assert spider.closed == ['dry_run_limit']


def test_spider_without_cinemas_attribute_still_closes(collector):
    """Fallback path for a spider that never declared its venues."""
    spider = FakeSpider('mystery')  # no `cinemas`
    for i in range(5):
        collector(spider, 'MYSTERY CINEMA', f'Film {i}')

    assert spider.closed == ['dry_run_limit']


def test_reset_clears_state_between_runs(collector):
    spider = FakeSpider('metrograph', ['METROGRAPH'])
    for i in range(5):
        collector(spider, 'METROGRAPH', f'Film {i}')

    DryRunCollectorPipeline.reset(3)
    assert DryRunCollectorPipeline.items == []
    assert DryRunCollectorPipeline._seen == {}

    spider2 = FakeSpider('metrograph', ['METROGRAPH'])
    DryRunCollectorPipeline().process_item(
        {'cinema': 'METROGRAPH', 'title': 'Fresh Film'}, spider2
    )
    assert spider2.closed == []
    assert _titles('METROGRAPH') == {'Fresh Film'}


def test_titles_are_whitespace_normalized(collector):
    """A \\xa0 variant must not count as a second distinct movie."""
    spider = FakeSpider('film_forum', ['FILM FORUM'])
    collector(spider, 'FILM FORUM', 'REUNION')
    collector(spider, 'FILM FORUM', 'REUNION\xa0')

    assert _titles('FILM FORUM') == {'REUNION'}
