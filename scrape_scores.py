"""
College Baseball Score Scraper
Pulls live game scores from ESPN's public API.
Focuses on SEC games but can show all D1 baseball.
"""

import requests
from datetime import datetime
import json
import sys


ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard"

# SEC team abbreviations for filtering
SEC_ABBRS = {
    "ALA", "ARK", "AUB", "FLA", "UGA",
    "UK", "LSU", "MSST", "MIZ", "MISS",
    "OU", "SC", "TENN", "TEX",
    "TA&M", "VAN",
}


def fetch_scoreboard(date=None, limit=100, conference=None):
    """Fetch the ESPN scoreboard for college baseball.

    Args:
        date: Date string in YYYYMMDD format. Defaults to today.
        limit: Max number of games to return.
        conference: ESPN conference ID to filter (8 = SEC).
    """
    params = {"limit": limit}
    if date:
        params["dates"] = date
    if conference:
        params["groups"] = conference

    resp = requests.get(ESPN_SCOREBOARD_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def parse_games(data):
    """Parse ESPN API response into a clean list of game dicts."""
    games = []
    for event in data.get("events", []):
        competition = event["competitions"][0]
        competitors = competition["competitors"]

        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        game = {
            "id": event["id"],
            "date": event["date"],
            "status": competition["status"]["type"]["description"],
            "detail": competition["status"]["type"]["detail"],
            "period": competition["status"].get("period", 0),
            "inning_state": competition["status"].get("type", {}).get("shortDetail", ""),
            "home_team": home["team"]["displayName"],
            "home_abbr": home["team"]["abbreviation"],
            "home_score": int(home.get("score", 0)),
            "home_rank": home.get("curatedRank", {}).get("current", 99),
            "away_team": away["team"]["displayName"],
            "away_abbr": away["team"]["abbreviation"],
            "away_score": int(away.get("score", 0)),
            "away_rank": away.get("curatedRank", {}).get("current", 99),
        }
        games.append(game)

    return games


def is_sec_game(game):
    """Check if at least one team in the game is an SEC team."""
    return game["home_abbr"] in SEC_ABBRS or game["away_abbr"] in SEC_ABBRS


def format_team(name, abbr, score, rank):
    """Format a team line with optional ranking."""
    rank_str = f"#{rank} " if rank <= 25 else ""
    return f"{rank_str}{name} ({abbr})  {score}"


def display_games(games, title="Games"):
    """Pretty-print a list of games to the terminal."""
    if not games:
        print(f"\n  No {title.lower()} found.\n")
        return

    print(f"\n{'=' * 60}")
    print(f"  {title}  ({len(games)} games)")
    print(f"{'=' * 60}")

    for g in games:
        print(f"\n  {g['inning_state']:<30} [{g['status']}]")
        print(f"    {format_team(g['away_team'], g['away_abbr'], g['away_score'], g['away_rank'])}")
        print(f"    {format_team(g['home_team'], g['home_abbr'], g['home_score'], g['home_rank'])}")

    print(f"\n{'=' * 60}\n")


def main():
    # Parse optional date argument (YYYYMMDD)
    date = None
    sec_only = "--sec" in sys.argv
    show_json = "--json" in sys.argv

    for arg in sys.argv[1:]:
        if arg.isdigit() and len(arg) == 8:
            date = arg

    if not date:
        date = datetime.now().strftime("%Y%m%d")

    print(f"Fetching college baseball scores for {date}...")

    # Fetch all games, filter SEC client-side by abbreviation
    data = fetch_scoreboard(date=date)
    games = parse_games(data)

    if show_json:
        print(json.dumps(games, indent=2))
        return

    if sec_only:
        games = [g for g in games if is_sec_game(g)]
        display_games(games, title=f"SEC Games — {date}")
    else:
        sec_games = [g for g in games if is_sec_game(g)]
        other_games = [g for g in games if not is_sec_game(g)]

        display_games(sec_games, title=f"SEC Games — {date}")
        display_games(other_games, title=f"Other D1 Games — {date}")

    print(f"Total games fetched: {len(games)}")


if __name__ == "__main__":
    main()
