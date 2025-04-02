from database.routes import get_showtimes
from flask_cors import CORS
from flask import Flask, render_template, request, jsonify
import ollama

from database.setup_db import setup_database

# Initialize the database
setup_database()

app = Flask(__name__)
# CORS(app, resources={r"/*": {"origins": "http://your-frontend-domain.com"}})

@app.route('/')
def index():
    showtimes = get_showtimes()  # Fetch movie data
    print(f"Showtimes passed to template: {showtimes}")  # Debug print
    return render_template('index.html', showtimes=showtimes)

@app.route('/recommend', methods=['POST'])
def recommend():
    """Generate movie recommendations using Ollama."""
    user_input = request.json.get("query", "Recommend 5 movies")
    
    # Fetch showtimes and format them for the prompt
    showtimes = get_showtimes()
    formatted_showtimes = "\n".join(
        f"{movie['title']} | {movie['showdate']} | {movie['showtime']} | {movie['show_day']} | "
        f"{movie['director']} | {movie['year']} | {movie['runtime']} | {movie['format']}"
        for movie in showtimes
    )

    # Generate a recommendation prompt
    prompt = f"""You are a movie expert. Based on the available showtimes, 
    recommend 5 movies. Here is the list of upcoming showtimes: 
    
    {formatted_showtimes}

    The showtimes should be returned exactly in the following list format, without header or any additional information:

    Title | Show Date | Show Time | Day | Director | Year | Runtime | Format

    """

    # Call the LLM
    response = ollama.chat(model="llama3.2:latest", messages=[{"role": "user", "content": prompt}])
    
    # Extract LLM response
    # recommended_movies = response["message"]["content"].split("\n")[:5]  # Top 5
    recommended_movies = response["message"]["content"].split("\n")

    return jsonify({"recommendations": recommended_movies})

if __name__ == '__main__':
    app.run(debug=True)