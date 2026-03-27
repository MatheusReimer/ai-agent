"""
Fetches real-time sharp sportsbook odds from The Odds API and converts them
to vig-free implied probabilities. These serve as the "oracle" truth signal
for Polymarket arbitrage — no LLM inference needed for probability estimation.

Sharp books (Pinnacle, Betfair Exchange) have quant teams and real-time feeds.
Their lines are better calibrated than any LLM. We exploit Polymarket's lag.
"""

import requests
from config import ODDS_API_KEY

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# The Odds API sport keys → human labels
# Comment out any sport you don't want to query (saves API quota)
ACTIVE_SPORTS = {
    # --- Esports ---
    "esports_cs2":       "CS2",
    "esports_lol":       "League of Legends",
    "esports_dota2":     "Dota 2",
    "esports_valorant":  "Valorant",
    # --- Traditional Sports ---
    "baseball_mlb":              "MLB",
    "basketball_nba":            "NBA",
    "americanfootball_nfl":      "NFL",
    "soccer_epl":                "EPL",
    "soccer_usa_mls":            "MLS",
}

# Preferred bookmakers in priority order (sharpest first)
# Pinnacle is the gold standard — they accept sharp money and don't limit winners
PREFERRED_BOOKS = ["pinnacle", "betfair_ex_eu", "draftkings", "fanduel", "betmgm"]


def _remove_vig(raw_probs: dict) -> dict:
    """
    Normalise raw implied probabilities (from decimal odds) to remove the bookmaker's
    overround (vig). This gives the book's best estimate of true probability.

    Example: {TeamA: 0.55, TeamB: 0.50} (overround 1.05) → {TeamA: 0.524, TeamB: 0.476}
    """
    total = sum(raw_probs.values())
    if total == 0:
        return raw_probs
    return {k: round(v / total, 4) for k, v in raw_probs.items()}


def _pick_sharpest_book(bookmakers: list) -> dict | None:
    """Return the sharpest available bookmaker from the event's bookmaker list."""
    book_map = {bm["key"]: bm for bm in bookmakers}
    for preferred in PREFERRED_BOOKS:
        if preferred in book_map:
            return book_map[preferred]
    # Fall back to first available
    return bookmakers[0] if bookmakers else None


def get_sharp_odds(sports: list | None = None) -> list[dict]:
    """
    Query The Odds API for the specified sports and return vig-free probabilities.

    Args:
        sports: list of sport keys to query (defaults to all ACTIVE_SPORTS)

    Returns:
        List of dicts, each representing one matchup:
        {
            sport, sport_key, home_team, away_team, commence_time,
            bookmaker,
            probabilities: {team_name: float}  ← vig-removed
        }
    """
    if not ODDS_API_KEY:
        print("  ⚠️  ODDS_API_KEY not configured — sportsbook arb disabled.")
        print("       Set ODDS_API_KEY in your .env to enable.")
        return []

    if sports is None:
        sports = list(ACTIVE_SPORTS.keys())

    all_events = []
    print(f"  Fetching sharp odds for {len(sports)} sport(s)...")

    for sport_key in sports:
        try:
            resp = requests.get(
                f"{ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey":      ODDS_API_KEY,
                    "regions":     "us,eu",
                    "markets":     "h2h",
                    "oddsFormat":  "decimal",
                    "bookmakers":  ",".join(PREFERRED_BOOKS),
                },
                timeout=12,
            )

            if resp.status_code == 404:
                # Sport not currently in season or no events
                continue
            resp.raise_for_status()

            events = resp.json()
            matched_count = 0

            for event in events:
                book = _pick_sharpest_book(event.get("bookmakers", []))
                if not book:
                    continue

                h2h = next((m for m in book["markets"] if m["key"] == "h2h"), None)
                if not h2h or not h2h.get("outcomes"):
                    continue

                # Convert decimal odds → raw implied prob
                raw = {o["name"]: 1 / o["price"] for o in h2h["outcomes"] if o.get("price", 0) > 0}
                if not raw:
                    continue

                probs = _remove_vig(raw)

                all_events.append({
                    "sport":          ACTIVE_SPORTS.get(sport_key, sport_key),
                    "sport_key":      sport_key,
                    "home_team":      event.get("home_team", ""),
                    "away_team":      event.get("away_team", ""),
                    "commence_time":  event.get("commence_time", ""),
                    "bookmaker":      book["title"],
                    "probabilities":  probs,
                })
                matched_count += 1

            if matched_count:
                print(f"    {ACTIVE_SPORTS.get(sport_key, sport_key)}: {matched_count} event(s)")

        except requests.exceptions.HTTPError as e:
            print(f"    ⚠️  {sport_key}: HTTP {e.response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"    ⚠️  {sport_key}: {e}")
        except Exception as e:
            print(f"    ⚠️  {sport_key}: unexpected error — {e}")

    print(f"  Sharp odds fetched: {len(all_events)} total matchups across all sports.")
    return all_events
