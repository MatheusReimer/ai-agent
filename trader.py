from config import PRIVATE_KEY, POLYMARKET_PROXY_ADDRESS
from eth_utils import to_checksum_address

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs
except ImportError:
    ClobClient = None
    print("⚠️ Warning: 'py_clob_client' library not found. Trading functionality will be limited.")

MIN_SHARES = 5

def _resolve_primary(question, market_data_map):
    """Find the best-matching sub-market for a question string."""
    q_words = set(question.lower().split())
    best_event, best_score = None, 0
    for event in market_data_map:
        candidates = [event.get("title", "")] + [m.get("question", "") for m in event.get("markets", [])]
        for text in candidates:
            score = len(q_words & set(text.lower().split()))
            if score > best_score:
                best_score = score
                best_event = event
    if not best_event or best_score < max(2, len(q_words) * 0.4):
        return None, None
    best_primary, best_primary_score = best_event.get("markets", [{}])[0], 0
    for m in best_event.get("markets", []):
        score = len(q_words & set(m.get("question", "").lower().split()))
        if score > best_primary_score:
            best_primary_score = score
            best_primary = m
    return best_event, best_primary


def _parse_json_field(value):
    import json as _json
    if isinstance(value, str):
        return _json.loads(value)
    return value


def validate_portfolio(portfolio, market_data_map):
    """
    Check each bet against live market data before execution.
    Returns a filtered list of valid bets and prints a pre-flight summary.
    """
    print("\n--- PRE-FLIGHT VALIDATION ---")
    valid, skipped = [], []

    for bet in portfolio:
        question = bet.get("market_question", "")
        amount   = float(bet.get("amount", 0))
        outcome  = bet.get("outcome", "")
        reason   = None

        if amount <= 0:
            reason = "zero amount"
        else:
            _, primary = _resolve_primary(question, market_data_map)
            if not primary:
                reason = "market not found in fetched data"
            else:
                try:
                    outcomes   = _parse_json_field(primary.get("outcomes", []))
                    prices     = _parse_json_field(primary.get("outcomePrices", ["0.5"]))
                    out_lower  = outcome.lower()
                    idx = next(i for i, o in enumerate(outcomes)
                               if o.lower() in out_lower or out_lower in o.lower())
                    price      = float(prices[idx])
                    fill_price = min(round(price * 1.05, 4), 0.97)
                    min_amount = round(MIN_SHARES * fill_price, 2)

                    if price <= 0.001 or price >= 0.999:
                        reason = f"price {price:.3f} — market resolved or invalid"
                    elif price >= 0.90:
                        reason = f"price {price:.3f} — odds too short (max return {(1/price - 1)*100:.0f}%, not worth the risk)"
                    elif amount < min_amount:
                        # Auto-bump to minimum instead of skipping
                        print(f"  ⚠️  BUMP  ${amount:.2f} → ${min_amount:.2f} on {outcome} | {question[:50]} (min for {MIN_SHARES} shares at fill {fill_price:.4f})")
                        bet["amount"] = min_amount
                except StopIteration:
                    reason = f"outcome '{outcome}' not found in market"
                except Exception as e:
                    reason = str(e)

        if reason:
            skipped.append((bet, reason))
            print(f"  ❌ SKIP  ${amount:.2f} on {outcome} | {question[:50]} → {reason}")
        else:
            valid.append(bet)
            print(f"  ✅ OK    ${amount:.2f} on {outcome} | {question[:50]}")

    print(f"\n  {len(valid)} valid / {len(skipped)} skipped out of {len(portfolio)} bets")
    return valid


def execute_portfolio(portfolio, market_data_map, balance=None):
    """
    Iterates through the AI's portfolio and places orders on Polymarket.
    Returns list of successfully placed bets.
    """
    if not PRIVATE_KEY:
        print("Skipping trading: No PRIVATE_KEY found in .env")
        return []

    if ClobClient is None:
        print("❌ Cannot initialize Trader: 'py_clob_client' is missing.")
        print("   -> Run: pip install py-clob-client")
        return

    print("\n--- INITIALIZING TRADING ENGINE ---")
    
    # Initialize the Polymarket Client
    # Note: host and chain_id depend on whether you are on Mainnet or Testnet
    # For Mainnet (Real Money): host="https://clob.polymarket.com", chain_id=137
    try:
        proxy_addr = to_checksum_address(POLYMARKET_PROXY_ADDRESS) if POLYMARKET_PROXY_ADDRESS else None
        
        client = ClobClient(
            host="https://clob.polymarket.com", 
            key=PRIVATE_KEY, 
            chain_id=137,
            funder=proxy_addr,
            signature_type=1 if proxy_addr else 0
        )
        client.set_api_creds(client.create_or_derive_api_creds())
    except Exception as e:
        print(f"Failed to initialize Trader: {e}")
        return []

    placed = []
    remaining = float(balance) if balance else None

    for bet in portfolio:
        question = bet.get("market_question")
        amount   = float(bet.get("amount", 0))
        outcome  = bet.get("outcome")

        if not amount or amount <= 0:
            print(f"  -> Skipping: zero amount bet on '{question}'")
            continue
        print(f"Processing bet: ${amount} on {outcome} for '{question}'")

        # 1. Find the matching event + primary market sub-object via word overlap
        q_words = set(question.lower().split())
        best_event, best_score = None, 0
        for event in market_data_map:
            candidates = [event.get("title", "")]
            for m in event.get("markets", []):
                candidates.append(m.get("question", ""))
            for text in candidates:
                score = len(q_words & set(text.lower().split()))
                if score > best_score:
                    best_score = score
                    best_event = event

        print(f"  -> Looking up market data for: {question}")
        if not best_event or best_score < max(2, len(q_words) * 0.4):
            print(f"  -> Error: Could not find market data for '{question}'")
            continue

        # Pick the sub-market whose question best matches the bet question
        best_primary, best_primary_score = best_event.get("markets", [{}])[0], 0
        for m in best_event.get("markets", []):
            score = len(q_words & set(m.get("question", "").lower().split()))
            if score > best_primary_score:
                best_primary_score = score
                best_primary = m
        primary = best_primary

        # 2. Find token ID by matching outcome name (fuzzy: contains match)
        try:
            import json as _json
            outcomes  = primary.get("outcomes", [])
            token_ids = primary.get("clobTokenIds", [])
            if isinstance(outcomes, str):
                outcomes = _json.loads(outcomes)
            if isinstance(token_ids, str):
                token_ids = _json.loads(token_ids)
            outcome_lower = outcome.lower()
            outcome_index = next(
                i for i, o in enumerate(outcomes)
                if o.lower() in outcome_lower or outcome_lower in o.lower()
            )
            token_id = token_ids[outcome_index]
            raw_prices = primary.get("outcomePrices", ["0.5"])
            if isinstance(raw_prices, str):
                raw_prices = _json.loads(raw_prices)
            price = float(raw_prices[outcome_index])
            bet["condition_id"]  = primary.get("conditionId")
            bet["outcome_index"] = outcome_index
            print(f"  -> Found Token ID: {token_id} (Outcome: {outcome}, Price: {price:.3f})")
        except (StopIteration, IndexError, KeyError):
            print(f"  -> Error: Could not determine Token ID for outcome '{outcome}'. Available: {outcomes}")
            continue

        if price <= 0.001 or price >= 0.999:
            print(f"  -> Skipping: price is {price:.3f} — market already resolved or invalid.")
            continue

        MIN_SHARES = 5
        # Use fill_price (slightly above market) to cross the spread
        fill_price = min(round(price * 1.05, 4), 0.97)
        # Size must be based on fill_price so actual spend = amount
        size = round(amount / fill_price, 2)
        if size < MIN_SHARES:
            size = MIN_SHARES
            amount = round(MIN_SHARES * fill_price, 2)
            print(f"  -> Auto-adjusting to minimum: {size} shares at {fill_price:.4f} (${amount:.2f})")

        # If remaining balance is less than allocated but still covers minimum, use what's left
        if remaining is not None and amount > remaining:
            min_cost = round(MIN_SHARES * fill_price, 2)
            if remaining >= min_cost:
                print(f"  -> Adjusting to remaining balance: ${amount:.2f} → ${remaining:.2f}")
                amount = remaining
                size = round(amount / fill_price, 2)
            else:
                print(f"  -> Skipping: remaining ${remaining:.2f} below minimum ${min_cost:.2f}")
                continue

        # Place Order
        try:
            print(f"  -> Preparing order: {size} shares at {fill_price:.4f} (${amount:.2f})...")
            resp = client.create_and_post_order(
                OrderArgs(
                    price=fill_price,
                    size=size,
                    side="BUY",
                    token_id=token_id
                )
            )
            print(f"  -> 🚀 Order Placed! ID: {resp.get('orderID')}")
            bet["amount"] = amount  # update with actual spent amount
            placed.append(bet)
            if remaining is not None:
                remaining = round(remaining - amount, 4)
                print(f"  -> Remaining balance: ${remaining:.2f}")
        except Exception as e:
            print(f"  -> Trade Failed: {e}")

    print(f"\n  ✅ {len(placed)} order(s) placed successfully.")
    return placed