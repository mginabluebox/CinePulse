from flask import Flask, render_template
from database import get_showtimes

app = Flask(__name__)

@app.route('/')
def index():
    showtimes = get_showtimes()  # Fetch movie data
    return render_template('index.html', showtimes=showtimes)

if __name__ == '__main__':
    app.run(debug=True)