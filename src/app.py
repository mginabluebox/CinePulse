from database.queries import get_showtimes
from database.setup_db import get_engine
from flask import Flask, render_template, request, jsonify

from bots.get_recommendation import recommend_movies, recommend_movies_by_embedding
from errors import LLMError, DBError, ParseError

app = Flask(__name__, template_folder='templates', static_folder='static')

@app.route('/')
def index():
    showtimes = get_showtimes(interval_days=14)  # Fetch movie data
    return render_template('index.html', showtimes=showtimes)

engine = get_engine()

# Archived legacy endpoint: /api/recommend previously used showtime-based LLM flow.
# Keeping route for compatibility but returning 410 to signal deprecation.
@app.route('/api/recommend', methods=['POST'])
def api_recommend():
    return jsonify({'error': 'This endpoint is archived; use /api/recommend_movies instead.'}), 410


@app.route('/api/recommend_movies', methods=['POST'])
def api_recommend_movies():
    preference = request.get_json(force=True).get('preference') or ''
    try:
        result = recommend_movies_by_embedding(preference, engine)
        return jsonify(result), 200
    except Exception as e:
        app.logger.exception('Error in /api/recommend_movies')
        msg = str(e)
        status = 500
        if isinstance(e, (LLMError, DBError, ParseError)):
            status = 502
        return jsonify({'error': msg}), status

if __name__ == '__main__':
    app.run(debug=True)