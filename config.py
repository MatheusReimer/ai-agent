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

# Define categories and their specific filtering rules
# tag_id values sourced directly from Polymarket /sports endpoint
CATEGORIES = [
    # --- Esports (LLM edge detection) ---
    {"slug": "league-of-legends", "tag_id": 39,    "filter_match": True, "limit": 25},
    {"slug": "cs2",               "tag_id": 37,    "filter_match": True, "limit": 30},
    ## {"slug": "valorant",        "tag_id": 40,    "filter_match": True, "limit": 20},
    ## {"slug": "dota2",           "tag_id": 38,    "filter_match": True, "limit": 20},

    # --- Traditional Sports (sportsbook arb via The Odds API) ---
    {"slug": "mlb",  "tag_id": 8,  "filter_match": True, "limit": 15},
    {"slug": "nba",  "tag_id": 34, "filter_match": True, "limit": 10},
    {"slug": "epl",  "tag_id": 2,  "filter_match": True, "limit": 10},
    {"slug": "mls",  "tag_id": 33, "filter_match": True, "limit": 10},
    ## {"slug": "nfl", "tag_id": 10, "filter_match": True, "limit": 10},
]

HTML_FILENAME = "esports_analysis.html"