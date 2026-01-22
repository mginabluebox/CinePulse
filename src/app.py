from database.queries import get_showtimes
from database.setup_db import get_engine, setup_database
from flask_cors import CORS
from flask import Flask, render_template, request, jsonify

from recommendation.core import recommend_movies
from errors import LLMError, DBError, ParseError
import logging

# Initialize the database
setup_database()

app = Flask(__name__, template_folder='templates', static_folder='static')

@app.route('/')
def index():
    showtimes = get_showtimes(14)  # Fetch movie data
    return render_template('index.html', showtimes=showtimes)

engine = get_engine()

@app.route('/api/recommend', methods=['POST'])
def api_recommend():
    data = request.get_json(force=True)
    mood = data.get('mood', '') or ''
    try:
        result = recommend_movies(mood, engine)
        # successful result should be a list of recommendation objects
        return jsonify(result), 200
    except Exception as e:
        # Log the full exception for server-side debugging
        app.logger.exception('Error in /api/recommend')
        msg = str(e)
        # Map typed upstream errors to 502 (LLM/DB/parse) while leaving others as 500
        status = 500
        if isinstance(e, (LLMError, DBError, ParseError)):
            status = 502
        return jsonify({'error': msg}), status

if __name__ == '__main__':
    app.run(debug=True)