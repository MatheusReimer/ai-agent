import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Your Polymarket Private Key (Starts with 0x...)
# This is the key used to sign transactions and access your Polymarket Proxy Wallet.
PRIVATE_KEY = os.getenv("POLYMARKET_KEY")
PURCHASE_PASSKEY = os.getenv("PURCHASE_PASSKEY")
# (Optional) The Proxy Wallet Address if using Email/Magic Link login
POLYMARKET_PROXY_ADDRESS = os.getenv("POLYMARKET_PROXY_ADDRESS")

# Define categories and their specific filtering rules
# tag_id values sourced directly from Polymarket /sports endpoint (sport.tags field)
CATEGORIES = [
    {"slug": "league-of-legends", "tag_id": 65,     "filter_match": True, "limit": 25},
    ##{"slug": "valorant",          "tag_id": 101672,  "filter_match": True, "limit": 20},
    {"slug": "cs2",               "tag_id": 100780,  "filter_match": True, "limit": 50},
    ##{"slug": "dota-2",            "tag_id": 102366,  "filter_match": True, "limit": 50},
]

HTML_FILENAME = "esports_analysis.html"