from database.queries import get_showtimes
from database.setup_db import get_engine, setup_database
from flask_cors import CORS
from flask import Flask, render_template, request, jsonify

from recommendation.core import recommend_movies

# Initialize the database
setup_database()

app = Flask(__name__, template_folder='templates', static_folder='static')
# CORS(app, resources={r"/*": {"origins": "http://your-frontend-domain.com"}})

@app.route('/')
def index():
    showtimes = get_showtimes(14)  # Fetch movie data
    return render_template('index.html', showtimes=showtimes)

engine = get_engine()

@app.route('/api/recommend', methods=['POST'])
def api_recommend():
    data = request.get_json(force=True)
    liked = data.get('liked_movies', '') or ''
    mood = data.get('mood', '') or ''
    try:
        result = recommend_movies(liked, mood, engine)
        return result, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(debug=True)