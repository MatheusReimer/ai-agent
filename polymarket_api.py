import requests
import time
from datetime import datetime, timezone, timedelta
from config import CATEGORIES

MAX_DAYS_TO_RESOLVE = 3

def get_market_id(slug):
    """
    Fetches the internal ID for a category by checking /sports first, then /tags.
    """
    try:
        # 1. Check /sports (Top-level categories)
        url = "https://gamma-api.polymarket.com/sports"
        # print(f"DEBUG: Checking /sports for '{slug}'...")
        response = requests.get(url)
        response.raise_for_status()
        sports = response.json()
        
        for sport in sports:
            if str(sport.get('sport')).lower() == slug.lower():
                return sport.get('id')

        # 2. Fallback to /tags (Specific games)
        url = "https://gamma-api.polymarket.com/tags"
        # print(f"DEBUG: Checking /tags for '{slug}'...")
        response = requests.get(url, params={"limit": 1000})
        response.raise_for_status()
        tags = response.json()
        
        for tag in tags:
            t_slug = str(tag.get('slug')).lower()
            t_label = str(tag.get('label')).lower()
            
            if slug.lower() in [t_slug, t_label]:
                return tag.get('id')

        # 3. Fallback: Reverse lookup via Market Search
        # print(f"DEBUG: Performing reverse lookup for '{slug}' via market search...")
        url = "https://gamma-api.polymarket.com/events"
        params = {"q": slug, "limit": 5, "closed": "false"}
        response = requests.get(url, params=params)
        response.raise_for_status()
        events = response.json()
        
        for event in events:
            for tag in event.get('tags', []):
                if tag.get('slug') == 'esports': continue
                return tag.get('id')

        print(f"Warning: ID for '{slug}' not found.")
    except Exception as e:
        print(f"Error fetching metadata: {e}")
    return None

def get_price_history(market_id):
    """
    Fetches historical prices (last 7 days) to analyze trends.
    """
    try:
        url = "https://gamma-api.polymarket.com/prices-history"
        params = {
            "market": market_id,
            "fidelity": 60, # 1 hour intervals roughly
            "limit": 168    # 7 days * 24 hours
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except Exception:
        return []

def calculate_technical_indicators(history_data):
    """
    Calculates RSI (Relative Strength Index) and Volatility from price history.
    """
    try:
        # Handle different API response formats (list vs dict with 'history' key)
        points = history_data.get("history", []) if isinstance(history_data, dict) else history_data
        
        if not points or len(points) < 15:
            return {"rsi": 50, "volatility": 0}

        # Extract prices (Polymarket API usually uses 'p' for price)
        prices = [float(point.get("p", 0)) for point in points]
        
        # 1. Calculate Volatility (Standard Deviation of recent prices)
        mean_price = sum(prices) / len(prices)
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        volatility = variance ** 0.5

        # 2. Calculate RSI (14 periods)
        gains, losses = [], []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-14:]) / 14
        avg_loss = sum(losses[-14:]) / 14
        
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi = 100 - (100 / (1 + rs)) if avg_loss != 0 else 100
        
        return {"rsi": round(rsi, 2), "volatility": round(volatility, 4)}
    except Exception as e:
        print(f"Error calculating stats: {e}")
        return {"rsi": 50, "volatility": 0}

def get_markets():
    """
    Fetches active events from Polymarket's Gamma API for configured categories.
    """
    print("Fetching data from Polymarket...")
    all_markets = []
    url = "https://gamma-api.polymarket.com/events"

    for cat in CATEGORIES:
        slug = cat["slug"]
        series_id = cat.get("series_id")
        if not series_id:
            print(f"Skipping {slug}: series_id not configured.")
            continue

        print(f"Fetching markets for: {slug} (series_id={series_id})")

        params = {
            "limit": cat["limit"] * 5,  # fetch extra to account for filtering
            "active": "true",
            "closed": "false",
            "ascending": "true",
            "order": "endDate",   # soonest-resolving first so today's matches appear early
            "series_id": series_id,
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            print(f"  -> Found {len(data)} raw events for {slug} (series_id={series_id})")
            
            deadline = datetime.now(timezone.utc) + timedelta(days=MAX_DAYS_TO_RESOLVE)
            count = 0
            for market in data:
                if cat["filter_match"]:
                    title = market.get("title", "").lower()
                    if " vs " not in title and " vs. " not in title:
                        continue

                now = datetime.now(timezone.utc)

                # Skip markets that resolve too far in the future, already ended,
                # or are likely already in-progress (endDate within 2h buffer)
                end_date_str = market.get("endDate") or market.get("endDateIso")
                if end_date_str:
                    try:
                        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                        game_start_estimate = end_date - timedelta(hours=2)
                        if game_start_estimate < now or end_date > deadline:
                            continue
                    except ValueError:
                        pass
                
                # Fetch trend data for the primary market in this event
                try:
                    # Events usually contain a list of markets. We take the first one (usually the main winner market).
                    primary_market_id = market.get("markets", [{}])[0].get("id")
                    if primary_market_id:
                        print(f"    -> Fetching history for: {market.get('title')[:40]}...")
                        market["price_history"] = get_price_history(primary_market_id)
                        market["technical_analysis"] = calculate_technical_indicators(market["price_history"])
                except Exception as e:
                    print(f"Could not fetch history for {market.get('title')}: {e}")

                market["category"] = slug
                all_markets.append(market)
                count += 1
                if count >= cat["limit"]:
                    break
        except Exception as e:
            print(f"Error fetching data for {slug}: {e}")

    return all_markets