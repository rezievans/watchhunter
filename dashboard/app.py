import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, jsonify, render_template

app = Flask(__name__)

# Injected by main.py before starting Flask thread
db = None


@app.route("/")
def index():
    listings = db.get_all_listings(limit=500) if db else []
    sources = db.get_source_status() if db else []
    stats = db.get_stats() if db else {"total": 0, "today": 0}
    return render_template("index.html", listings=listings, sources=sources, stats=stats)


@app.route("/api/listings")
def api_listings():
    data = db.get_all_listings() if db else []
    return jsonify(data)


@app.route("/api/status")
def api_status():
    sources = db.get_source_status() if db else []
    stats = db.get_stats() if db else {}
    return jsonify({"sources": sources, "stats": stats})
