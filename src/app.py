from database.queries import get_showtimes
from database.setup_db import get_engine
from flask import Flask, render_template, request, jsonify
from flask_caching import Cache

from bots.get_recommendation import recommend_movies_by_embedding, search_showtimes_by_embedding
from database.queries import insert_recommendation_feedback
import uuid
from errors import LLMError, DBError, ParseError
from collections import defaultdict
from datetime import datetime, timedelta

app = Flask(__name__, template_folder='templates', static_folder='static')
cache = Cache(config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})
cache.init_app(app)

def parse_showtime_mins(t):
    """Convert a showtime string like '7:30 PM' to minutes from midnight for sorting."""
    if not t:
        return 9999
    try:
        parts = str(t).strip().upper().split(':')
        h = int(parts[0])
        rest = parts[1].split()
        mn = int(rest[0])
        ampm = rest[1] if len(rest) > 1 else None
        if ampm == 'PM' and h < 12:
            h += 12
        elif ampm == 'AM' and h == 12:
            h = 0
        return h * 60 + mn
    except Exception:
        return 9999


def showtime_period(mins):
    if mins < 720:
        return 'morning'
    elif mins < 1020:
        return 'afternoon'
    return 'evening'


def build_calendar(showtimes):
    cal = defaultdict(dict)
    day_labels = {}
    for row in (showtimes or []):
        date = row.get('showdate')
        key = row.get('movie_id') or row.get('title')
        if key not in cal[date]:
            cal[date][key] = {
                'title': row.get('title'),
                'director': row.get('director'),
                'year': row.get('year'),
                'runtime': row.get('runtime'),
                'synopsis': row.get('synopsis'),
                'image_url': row.get('image_url'),
                'showtimes': []
            }
        if not cal[date][key].get('image_url') and row.get('image_url'):
            cal[date][key]['image_url'] = row.get('image_url')
        if not cal[date][key].get('synopsis') and row.get('synopsis'):
            cal[date][key]['synopsis'] = row.get('synopsis')
        mins = parse_showtime_mins(row.get('showtime'))
        cal[date][key]['showtimes'].append({
            'showtime': row.get('showtime'),
            'cinema': row.get('cinema'),
            'format': row.get('format'),
            'ticket_link': row.get('ticket_link'),
            'period': showtime_period(mins),
            '_sort': mins,
        })
        day_labels[date] = row.get('show_day', '')

    result = []
    for date in sorted(cal.keys()):
        dt = datetime.strptime(date, '%Y-%m-%d')
        show_day = day_labels.get(date, '')
        day_abbr = show_day[:3].capitalize() if show_day else dt.strftime('%a')
        result.append({
            'date': date,
            'label': f"{day_abbr}, {dt.strftime('%b %-d')}",
            'show_day': show_day,
            'films': [
                dict(f, showtimes=sorted(f['showtimes'], key=lambda s: s['_sort']))
                for f in sorted(cal[date].values(), key=lambda f: min(s['_sort'] for s in f['showtimes']))
            ]
        })
    return result


@app.route('/')
@cache.cached(timeout=300)
def landing():
    showtimes = get_showtimes(interval_days=7, engine=engine)
    calendar = build_calendar(showtimes)
    return render_template('landing.html', calendar=calendar)


@app.route('/api/calendar_week2')
@cache.cached(timeout=300)
def api_calendar_week2():
    start = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d')
    showtimes = get_showtimes(start_date=start, end_date=end, engine=engine)
    calendar = build_calendar(showtimes)
    tabs_html = render_template('_week_tabs.html', calendar=calendar, day_offset=7)
    panels_html = render_template('_week_panels.html', calendar=calendar, day_offset=7)
    return jsonify({'tabs': tabs_html, 'panels': panels_html})


@app.route('/app')
def index():
    return render_template('index.html')

engine = get_engine()


@app.route('/api/recommend_movies', methods=['POST'])
def api_recommend_movies():
    body = request.get_json(force=True)
    preference = body.get('preference') or ''
    session_token = body.get('session_token')
    run_id = str(uuid.uuid4())
    try:
        result = recommend_movies_by_embedding(preference, engine, run_id=run_id, session_token=session_token)
        return jsonify({"run_id": run_id, "results": result}), 200
    except Exception as e:
        app.logger.exception('Error in /api/recommend_movies')
        msg = str(e)
        status = 500
        if isinstance(e, (LLMError, DBError, ParseError)):
            status = 502
        return jsonify({'error': msg}), status


@app.route('/api/search_showtimes', methods=['POST'])
def api_search_showtimes():
    query = request.get_json(force=True).get('query') or ''
    try:
        result = search_showtimes_by_embedding(query, engine)
        return jsonify(result), 200
    except Exception as e:
        app.logger.exception('Error in /api/search_showtimes')
        msg = str(e)
        status = 500
        if isinstance(e, (LLMError, DBError, ParseError)):
            status = 502
        return jsonify({'error': msg}), status


@app.route('/api/feedback', methods=['POST'])
def api_feedback():
    data = request.get_json(force=True) or {}
    movie_id = data.get('movie_id')
    liked = data.get('liked')
    if movie_id is None or liked is None:
        return jsonify({'error': 'movie_id and liked are required'}), 400

    try:
        insert_recommendation_feedback(
            run_id=data.get('run_id'),
            session_token=data.get('session_token'),
            movie_id=movie_id,
            liked=bool(liked),
            decision_ms=data.get('decision_ms'),
            similarity=data.get('similarity'),
            title=data.get('title'),
            year=data.get('year'),
            engine=engine,
        )
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        app.logger.exception('Error in /api/feedback')
        msg = str(e)
        status = 500
        if isinstance(e, (LLMError, DBError, ParseError)):
            status = 502
        return jsonify({'error': msg}), status

if __name__ == '__main__':
    app.run(debug=True)