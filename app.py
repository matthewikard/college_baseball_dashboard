"""
SEC Baseball Dashboard — Flask Server
Serves a live scoreboard dashboard and JSON API.
"""

from flask import Flask, render_template, jsonify, request
from datetime import datetime
from scrape_scores import (
    fetch_scoreboard, parse_games, is_sec_game,
    fetch_standings, fetch_series_record, enrich_games,
)

app = Flask(__name__)


@app.route("/")
def dashboard():
    """Serve the dashboard page."""
    date = request.args.get("date", datetime.now().strftime("%Y%m%d"))
    return render_template("dashboard.html", date=date)


@app.route("/api/scores")
def api_scores():
    """JSON API endpoint for SEC game scores with standings and series."""
    date = request.args.get("date", datetime.now().strftime("%Y%m%d"))

    try:
        data = fetch_scoreboard(date=date)
        games = parse_games(data)
        sec_games = [g for g in games if is_sec_game(g)]

        standings = fetch_standings()
        series = fetch_series_record(date, sec_games)
        sec_games = enrich_games(sec_games, standings, series)

        return jsonify({
            "date": date,
            "count": len(sec_games),
            "fetched_at": datetime.now().isoformat(),
            "games": sec_games,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/standings")
def api_standings():
    """JSON API endpoint for SEC standings."""
    try:
        standings = fetch_standings()
        sec_standings = [
            v for v in standings.values()
            if v.get("standing", 0) > 0
        ]
        sec_standings.sort(key=lambda t: t["standing"])

        return jsonify({
            "fetched_at": datetime.now().isoformat(),
            "standings": sec_standings,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
