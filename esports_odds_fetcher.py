"""
Fetches esports odds directly from Pinnacle's API.

Pinnacle is the sharpest esports sportsbook in the world — they accept sharp
money, don't limit winners, and are used as the industry's ground-truth line.
Their odds ARE the market consensus on true probability for esports matches.

Requires a free Pinnacle account. Set PINNACLE_USERNAME and PINNACLE_PASSWORD
in your .env file. Account creation: https://www.pinnacle.com

API docs: https://api.pinnacle.com/doc/
"""

import requests
from requests.auth import HTTPBasicAuth
from config import PINNACLE_USERNAME, PINNACLE_PASSWORD

BASE_URL = "https://api.pinnacle.com"

# Pinnacle sport IDs for esports titles we care about
# These are league-level filters — each game has many leagues (tournaments)
ESPORTS_SPORT_ID = 12  # Pinnacle's esports sport

# Map Pinnacle league name keywords → Polymarket category slug
# Used to tag matched odds with the right category for market_matcher.py
LEAGUE_CATEGORY_MAP = {
    "counter-strike": "cs2",
    "cs2":            "cs2",
    "cs:go":          "cs2",
    "league of legends": "league-of-legends",
    "lol":            "league-of-legends",
    "dota":           "dota2",
    "valorant":       "valorant",
}


def _category_from_league(league_name: str) -> str | None:
    name = league_name.lower()
    for keyword, slug in LEAGUE_CATEGORY_MAP.items():
        if keyword in name:
            return slug
    return None


def _remove_vig(raw_probs: dict) -> dict:
    """Strip overround from raw implied probabilities → true probability estimate."""
    total = sum(raw_probs.values())
    if total == 0:
        return raw_probs
    return {k: round(v / total, 4) for k, v in raw_probs.items()}


def _get(path: str, params: dict = None) -> dict | list | None:
    try:
        resp = requests.get(
            f"{BASE_URL}{path}",
            params=params,
            auth=HTTPBasicAuth(PINNACLE_USERNAME, PINNACLE_PASSWORD),
            headers={"Accept": "application/json"},
            timeout=12,
        )
        if resp.status_code == 401:
            print("  ⚠️  Pinnacle auth failed — check PINNACLE_USERNAME / PINNACLE_PASSWORD in .env")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Pinnacle API error ({path}): {e}")
        return None


def get_esports_odds() -> list[dict]:
    """
    Fetch all upcoming esports match odds from Pinnacle.

    Returns list of dicts:
    {
        sport:          "cs2" | "league-of-legends" | "dota2" | "valorant"
        league:         str  (tournament name)
        home_team:      str
        away_team:      str
        commence_time:  str  (ISO)
        bookmaker:      "Pinnacle"
        probabilities:  {team_name: float}  ← vig-removed
    }
    """
    if not PINNACLE_USERNAME or not PINNACLE_PASSWORD:
        print("  ⚠️  PINNACLE_USERNAME / PINNACLE_PASSWORD not set — esports arb disabled.")
        print("       Create a free account at pinnacle.com and add credentials to .env")
        return []

    # 1. Get all esports leagues
    leagues_data = _get("/v2/leagues", {"sportId": ESPORTS_SPORT_ID})
    if not leagues_data or "leagues" not in leagues_data:
        print("  ⚠️  Could not fetch Pinnacle esports leagues.")
        return []

    # Filter to only the games we care about
    target_leagues = []
    for league in leagues_data["leagues"]:
        name = league.get("name", "")
        category = _category_from_league(name)
        if category:
            target_leagues.append({"id": league["id"], "name": name, "category": category})

    if not target_leagues:
        print("  ⚠️  No matching esports leagues found on Pinnacle.")
        return []

    league_ids = [str(l["id"]) for l in target_leagues]
    league_map = {l["id"]: l for l in target_leagues}

    print(f"  Pinnacle esports leagues found: {len(target_leagues)}")

    # 2. Get fixtures (upcoming matches)
    fixtures_data = _get("/v3/fixtures", {
        "sportId":   ESPORTS_SPORT_ID,
        "leagueIds": ",".join(league_ids),
    })
    if not fixtures_data:
        return []

    # Build fixture lookup: eventId → {teams, time, leagueId}
    fixture_map = {}
    for league in fixtures_data.get("league", []):
        lid = league.get("id")
        for event in league.get("events", []):
            eid = event.get("id")
            fixture_map[eid] = {
                "home":       event.get("home", ""),
                "away":       event.get("away", ""),
                "starts":     event.get("starts", ""),
                "league_id":  lid,
                "league_name": league_map.get(lid, {}).get("name", ""),
                "category":   league_map.get(lid, {}).get("category", ""),
            }

    # 3. Get odds for those fixtures
    odds_data = _get("/v2/odds", {
        "sportId":    ESPORTS_SPORT_ID,
        "leagueIds":  ",".join(league_ids),
        "oddsFormat": "Decimal",
    })
    if not odds_data:
        return []

    results = []
    for league in odds_data.get("leagues", []):
        lid = league.get("id")
        for event in league.get("events", []):
            eid = event.get("id")
            fixture = fixture_map.get(eid)
            if not fixture:
                continue

            # Find moneyline (h2h) market
            moneyline = None
            for period in event.get("periods", []):
                if period.get("number") == 0:  # full match
                    moneyline = period.get("moneyline")
                    break

            if not moneyline:
                continue

            home_odds = moneyline.get("home")
            away_odds = moneyline.get("away")
            draw_odds = moneyline.get("draw")

            if not home_odds or not away_odds:
                continue

            # Convert decimal odds → raw implied probability
            raw = {
                fixture["home"]: 1 / home_odds,
                fixture["away"]: 1 / away_odds,
            }
            if draw_odds:
                raw["Draw"] = 1 / draw_odds

            probs = _remove_vig(raw)

            results.append({
                "sport":         fixture["category"],
                "sport_key":     fixture["category"],
                "league":        fixture["league_name"],
                "home_team":     fixture["home"],
                "away_team":     fixture["away"],
                "commence_time": fixture["starts"],
                "bookmaker":     "Pinnacle",
                "probabilities": probs,
            })

    print(f"  Pinnacle esports odds: {len(results)} upcoming matches.")
    return results
