import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# The Odds API key — get a free key at https://the-odds-api.com
# Free tier: 500 requests/month. Used to fetch sharp sportsbook lines as oracle truth.
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
# Your Polymarket Private Key (Starts with 0x...)
# This is the key used to sign transactions and access your Polymarket Proxy Wallet.
PRIVATE_KEY = os.getenv("POLYMARKET_KEY")
PURCHASE_PASSKEY = os.getenv("PURCHASE_PASSKEY")
# (Optional) The Proxy Wallet Address if using Email/Magic Link login
POLYMARKET_PROXY_ADDRESS = os.getenv("POLYMARKET_PROXY_ADDRESS")

# Define categories and their specific filtering rules.
# Use series_id (from Polymarket /sports endpoint "series" field) — more reliable than tag_id.
CATEGORIES = [
    # --- Esports (LLM edge detection) ---
    {"slug": "league-of-legends", "series_id": 10311, "filter_match": True, "limit": 25},
    {"slug": "cs2",               "series_id": 10310, "filter_match": True, "limit": 30},
    ## {"slug": "valorant",        "series_id": 10369, "filter_match": True, "limit": 20},
    ## {"slug": "dota2",           "series_id": 10309, "filter_match": True, "limit": 20},

    # --- Traditional Sports (sportsbook arb via The Odds API) ---
    {"slug": "mlb",  "series_id": 3,     "filter_match": True, "limit": 15},
    {"slug": "nba",  "series_id": 10345, "filter_match": True, "limit": 10},
    {"slug": "epl",  "series_id": 10188, "filter_match": True, "limit": 10},
    {"slug": "mls",  "series_id": 10189, "filter_match": True, "limit": 10},
    ## {"slug": "nfl", "series_id": 10187, "filter_match": True, "limit": 10},
]

HTML_FILENAME = "esports_analysis.html"