from database.queries import get_showtimes
from database.setup_db import get_engine
from flask import Flask, render_template, request, jsonify

from bots.get_recommendation import recommend_movies_by_embedding, search_showtimes_by_embedding
from database.queries import insert_recommendation_feedback
import uuid
from errors import LLMError, DBError, ParseError

app = Flask(__name__, template_folder='templates', static_folder='static')


def group_showtimes_by_movie(showtimes):
    """Group flat showtime rows by movie to simplify rendering."""
    grouped = []
    index = {}
    for row in showtimes or []:
        key = row.get("movie_id") or row.get("title")
        bucket = index.get(key)
        if bucket is None:
            bucket = {
                "movie_id": row.get("movie_id"),
                "title": row.get("title"),
                "director": row.get("director"),
                "year": row.get("year"),
                "runtime": row.get("runtime"),
                "synopsis": row.get("synopsis"),
                "image_url": row.get("image_url"),
                "showtimes": [],
            }
            grouped.append(bucket)
            index[key] = bucket

        if not bucket.get("image_url") and row.get("image_url"):
            bucket["image_url"] = row.get("image_url")

        bucket["showtimes"].append(
            {
                "id": row.get("id"),
                "showdate": row.get("showdate"),
                "showtime": row.get("showtime"),
                "show_day": row.get("show_day"),
                "format": row.get("format"),
                "cinema": row.get("cinema"),
                "ticket_link": row.get("ticket_link"),
            }
        )

    return grouped

@app.route('/')
def index():
    showtimes = get_showtimes(interval_days=14)  # Fetch movie data
    grouped_showtimes = group_showtimes_by_movie(showtimes)
    return render_template('index.html', showtimes=showtimes, grouped_showtimes=grouped_showtimes)

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