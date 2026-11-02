
from flask import Flask, render_template

# Create the Flask application.
app = Flask(__name__)


@app.route("/")
def home():
    # Render the main page of the auction website.
    return render_template("index.html")


# Start the development web server when this file is executed directly.
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
