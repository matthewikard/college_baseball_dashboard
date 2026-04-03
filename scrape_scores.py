"""
College Baseball Score Scraper
Pulls live game scores and standings from ESPN's public API.
Focuses on SEC games but can show all D1 baseball.
"""

import requests
from datetime import datetime, timedelta
from collections import defaultdict
import json
import sys


ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard"
ESPN_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/baseball/college-baseball/standings"
ESPN_TEAM_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/teams"

# SEC team abbreviations and ESPN team IDs
SEC_ABBRS = {
    "ALA", "ARK", "AUB", "FLA", "UGA",
    "UK", "LSU", "MSST", "MIZ", "MISS",
    "OU", "SC", "TENN", "TEX",
    "TA&M", "VAN",
}

SEC_TEAM_IDS = {
    "ALA": 148, "ARK": 58, "AUB": 55, "FLA": 75, "UGA": 78,
    "UK": 82, "LSU": 85, "MSST": 150, "MIZ": 91, "MISS": 92,
    "OU": 112, "SC": 193, "TENN": 199, "TEX": 126,
    "TA&M": 123, "VAN": 120,
}


def fetch_scoreboard(date=None, limit=100):
    """Fetch the ESPN scoreboard for college baseball.

    Args:
        date: Date string in YYYYMMDD format. Defaults to today.
        limit: Max number of games to return.
    """
    params = {"limit": limit}
    if date:
        params["dates"] = date

    resp = requests.get(ESPN_SCOREBOARD_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _fetch_team_conf_record(team_id, team_abbr, season=None):
    """Fetch a single SEC team's schedule and count conference W-L.

    Conference games are identified by both teams being in SEC_ABBRS.
    """
    if not season:
        season = datetime.now().year

    url = f"{ESPN_TEAM_URL}/{team_id}/schedule"
    resp = requests.get(url, params={"season": season}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    conf_wins = 0
    conf_losses = 0

    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed", False):
            continue

        competitors = comp.get("competitors", [])
        abbrs = [c["team"]["abbreviation"] for c in competitors]

        # Both teams must be SEC for it to be a conference game
        if not all(a in SEC_ABBRS for a in abbrs):
            continue

        us = next((c for c in competitors if c["team"]["abbreviation"] == team_abbr), None)
        if us and us.get("winner"):
            conf_wins += 1
        elif us:
            conf_losses += 1

    return conf_wins, conf_losses


def fetch_standings(season=None):
    """Fetch SEC standings with actual conference records from team schedules.

    Returns a dict keyed by team abbreviation with overall record,
    conference record, streak, and conference standing position.
    """
    if not season:
        season = datetime.now().year

    # Get overall stats from the standings endpoint
    params = {"season": season}
    resp = requests.get(ESPN_STANDINGS_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    standings = {}
    children = data.get("children", [])
    if not children:
        return standings

    entries = children[0].get("standings", {}).get("entries", [])

    # Build a lookup of overall stats for SEC teams
    overall_stats = {}
    for entry in entries:
        team = entry.get("team", {})
        abbr = team.get("abbreviation", "")
        if abbr not in SEC_ABBRS:
            continue

        stats = {s["name"]: s for s in entry.get("stats", [])}
        overall_stats[abbr] = {
            "name": team.get("displayName", ""),
            "overall": stats.get("overall", {}).get("summary", ""),
            "wins": int(stats.get("wins", {}).get("value", 0)),
            "losses": int(stats.get("losses", {}).get("value", 0)),
            "streak": stats.get("streak", {}).get("displayValue", ""),
        }

    # Fetch actual conference records from each team's schedule
    sec_entries = []
    for abbr, team_id in SEC_TEAM_IDS.items():
        try:
            conf_wins, conf_losses = _fetch_team_conf_record(team_id, abbr, season)
        except Exception:
            conf_wins, conf_losses = 0, 0

        base = overall_stats.get(abbr, {})
        conf_gp = conf_wins + conf_losses
        league_pct = conf_wins / conf_gp if conf_gp > 0 else 0.0

        team_data = {
            "abbr": abbr,
            "name": base.get("name", ""),
            "overall": base.get("overall", ""),
            "wins": base.get("wins", 0),
            "losses": base.get("losses", 0),
            "conf_record": f"{conf_wins}-{conf_losses}",
            "conf_wins": conf_wins,
            "conf_losses": conf_losses,
            "league_pct": league_pct,
            "streak": base.get("streak", ""),
            "standing": 0,
        }
        sec_entries.append(team_data)
        standings[abbr] = team_data

    # Sort by conference win pct (desc), then conf wins (desc), then overall wins (desc)
    sec_entries.sort(
        key=lambda t: (t["league_pct"], t["conf_wins"], t["wins"]),
        reverse=True,
    )
    for i, t in enumerate(sec_entries, 1):
        t["standing"] = i
        standings[t["abbr"]] = t

    return standings


def fetch_series_record(date_str, sec_games_today):
    """Find the current series record for each matchup on today's scoreboard.

    Looks at each SEC team's schedule to find consecutive games against the
    same opponent surrounding the given date. Handles Thu-Sat, Fri-Sun,
    rain-delay shifts, or any other scheduling pattern.

    Args:
        date_str: YYYYMMDD date string for the current scoreboard.
        sec_games_today: List of parsed SEC game dicts from today's scoreboard,
            used to know which matchups to look up.

    Returns a dict keyed by team abbreviation:
        {"ALA": {"label": "ALA 2-1 AUB", "wins": 2, "losses": 1, "opponent": "AUB"}, ...}
    """
    target_date = datetime.strptime(date_str, "%Y%m%d").date()

    # Collect the matchups we need to look up from today's games
    matchups_to_check = set()
    for g in sec_games_today:
        ha, aa = g["home_abbr"], g["away_abbr"]
        if ha in SEC_ABBRS and aa in SEC_ABBRS:
            matchups_to_check.add(tuple(sorted([ha, aa])))

    if not matchups_to_check:
        return {}

    # For each matchup, fetch one team's schedule and find the series
    series = {}
    for t1, t2 in matchups_to_check:
        team_id = SEC_TEAM_IDS.get(t1)
        if not team_id:
            continue

        try:
            url = f"{ESPN_TEAM_URL}/{team_id}/schedule"
            resp = requests.get(url, params={"season": target_date.year}, timeout=10)
            resp.raise_for_status()
            schedule = resp.json()
        except Exception:
            continue

        # Pull all games vs the opponent, sorted by date
        vs_games = []
        for event in schedule.get("events", []):
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            abbrs = {c["team"]["abbreviation"] for c in competitors}
            if t2 not in abbrs:
                continue

            game_date_str = event.get("date", "")[:10]  # "2026-03-28T..."
            try:
                game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            completed = comp.get("status", {}).get("type", {}).get("completed", False)
            us = next((c for c in competitors if c["team"]["abbreviation"] == t1), None)
            winner = us.get("winner", False) if us else False

            vs_games.append({
                "date": game_date,
                "completed": completed,
                "t1_won": winner,
            })

        vs_games.sort(key=lambda g: g["date"])

        # Find consecutive runs (series) of games — a gap of 4+ days starts a new series
        series_groups = []
        current_group = []
        for g in vs_games:
            if current_group and (g["date"] - current_group[-1]["date"]).days > 3:
                series_groups.append(current_group)
                current_group = []
            current_group.append(g)
        if current_group:
            series_groups.append(current_group)

        # Find the series that contains the target date
        active_series = None
        for group in series_groups:
            first = group[0]["date"]
            last = group[-1]["date"]
            if first <= target_date <= last:
                active_series = group
                break

        if not active_series:
            continue

        # Tally wins from completed games in this series
        t1_wins = sum(1 for g in active_series if g["completed"] and g["t1_won"])
        t2_wins = sum(1 for g in active_series if g["completed"] and not g["t1_won"])

        label = f"{t1} {t1_wins}-{t2_wins} {t2}"
        series[t1] = {"label": label, "wins": t1_wins, "losses": t2_wins, "opponent": t2}
        series[t2] = {"label": label, "wins": t2_wins, "losses": t1_wins, "opponent": t1}

    return series


def parse_games(data):
    """Parse ESPN API response into a clean list of game dicts."""
    games = []
    for event in data.get("events", []):
        competition = event["competitions"][0]
        competitors = competition["competitors"]

        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        # Extract overall record from scoreboard
        home_records = home.get("records", [])
        away_records = away.get("records", [])
        home_record = home_records[0]["summary"] if home_records else ""
        away_record = away_records[0]["summary"] if away_records else ""

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
            "home_record": home_record,
            "away_team": away["team"]["displayName"],
            "away_abbr": away["team"]["abbreviation"],
            "away_score": int(away.get("score", 0)),
            "away_rank": away.get("curatedRank", {}).get("current", 99),
            "away_record": away_record,
        }
        games.append(game)

    return games


def is_sec_game(game):
    """Check if at least one team in the game is an SEC team."""
    return game["home_abbr"] in SEC_ABBRS or game["away_abbr"] in SEC_ABBRS


def enrich_games(games, standings, series):
    """Add standings and series data to each game dict."""
    for g in games:
        for side in ("home", "away"):
            abbr = g[f"{side}_abbr"]
            team_standing = standings.get(abbr, {})
            g[f"{side}_conf_record"] = team_standing.get("conf_record", "")
            g[f"{side}_standing"] = team_standing.get("standing", 0)
            g[f"{side}_streak"] = team_standing.get("streak", "")

        # Series record for this matchup
        home_series = series.get(g["home_abbr"])
        if home_series and home_series.get("opponent") == g["away_abbr"]:
            g["series_label"] = home_series["label"]
        else:
            g["series_label"] = ""

    return games


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
        if g.get("series_label"):
            print(f"  Series: {g['series_label']}")
        print(f"    {format_team(g['away_team'], g['away_abbr'], g['away_score'], g['away_rank'])}")
        print(f"      Record: {g.get('away_record', '')}  Conf: {g.get('away_conf_record', '')}  SEC #{g.get('away_standing', '?')}")
        print(f"    {format_team(g['home_team'], g['home_abbr'], g['home_score'], g['home_rank'])}")
        print(f"      Record: {g.get('home_record', '')}  Conf: {g.get('home_conf_record', '')}  SEC #{g.get('home_standing', '?')}")

    print(f"\n{'=' * 60}\n")


def main():
    date = None
    sec_only = "--sec" in sys.argv
    show_json = "--json" in sys.argv

    for arg in sys.argv[1:]:
        if arg.isdigit() and len(arg) == 8:
            date = arg

    if not date:
        date = datetime.now().strftime("%Y%m%d")

    print(f"Fetching college baseball scores for {date}...")

    data = fetch_scoreboard(date=date)
    games = parse_games(data)
    sec_games = [g for g in games if is_sec_game(g)]

    # Fetch standings and series for enrichment
    standings = fetch_standings()
    series = fetch_series_record(date, sec_games)

    if sec_only:
        games = enrich_games(sec_games, standings, series)
        if show_json:
            print(json.dumps(games, indent=2))
        else:
            display_games(games, title=f"SEC Games — {date}")
    else:
        sec_games = enrich_games(sec_games, standings, series)
        other_games = [g for g in games if not is_sec_game(g)]

        if show_json:
            print(json.dumps(sec_games, indent=2))
        else:
            display_games(sec_games, title=f"SEC Games — {date}")
            display_games(other_games, title=f"Other D1 Games — {date}")

    print(f"Total games fetched: {len(games)}")


if __name__ == "__main__":
    main()
