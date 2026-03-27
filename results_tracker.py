import json
import requests
from datetime import datetime, timezone
from pathlib import Path

HISTORY_FILE = "bet_history.json"

PERSONAS = ["Form Edge", "Mispriced Favorite", "Underdog Value", "Momentum", "Contrarian", "Information Edge", "Unknown"]


def _load():
    if not Path(HISTORY_FILE).exists():
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def _find_market(question, markets):
    """Match a Gemini question string to a market event dict via word overlap."""
    q_words = set(question.lower().split())
    best_event, best_score = None, 0

    for event in markets:
        candidates = [event.get("title", "")]
        for m in event.get("markets", []):
            candidates.append(m.get("question", ""))

        for text in candidates:
            common = len(q_words & set(text.lower().split()))
            if common > best_score:
                best_score = common
                best_event = event

    return best_event if best_score >= max(2, len(q_words) * 0.4) else None


def _get_price_at_bet(bet, event):
    """Look up the current market price for the bet's outcome."""
    try:
        primary = event.get("markets", [{}])[0]
        import json as _json
        outcomes = primary.get("outcomes", ["Yes", "No"])
        prices   = primary.get("outcomePrices", [])
        if isinstance(outcomes, str):
            outcomes = _json.loads(outcomes)
        if isinstance(prices, str):
            prices = _json.loads(prices)
        idx = [o.lower() for o in outcomes].index(bet["outcome"].lower())
        return float(prices[idx])
    except Exception:
        return None


def record_bets(portfolio, markets):
    """Append newly placed bets to bet_history.json."""
    history  = _load()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    for bet in portfolio:
        event    = _find_market(bet.get("market_question", ""), markets)
        market_id = event["markets"][0].get("id") if event and event.get("markets") else None
        price    = _get_price_at_bet(bet, event) if event else None

        history.append({
            "timestamp":       timestamp,
            "market_question": bet.get("market_question"),
            "market_id":       market_id,
            "condition_id":    bet.get("condition_id"),
            "outcome_index":   bet.get("outcome_index"),
            "outcome_bet":     bet.get("outcome"),
            "amount":          bet.get("amount"),
            "price_at_bet":    price,
            "primary_backer":  bet.get("primary_backer", "Unknown"),
            "rationale":       bet.get("rationale", ""),
            "resolved":        False,
            "won":             None,
            "payout":          None,
            "net_profit":      None,
            "redeemed":        False,
        })

    _save(history)
    print(f"📝 Recorded {len(portfolio)} bets to {HISTORY_FILE}.")


def _resolve_entry(entry):
    """Try to resolve a single pending bet via the Polymarket API."""
    market_id = entry.get("market_id")
    if not market_id:
        return

    try:
        data = requests.get(
            f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=10
        ).json()

        outcomes = data.get("outcomes", [])
        prices   = data.get("outcomePrices", [])
        if isinstance(outcomes, str):
            import json as _j; outcomes = _j.loads(outcomes)
        if isinstance(prices, str):
            import json as _j; prices = _j.loads(prices)

        # Consider resolved if market is closed OR if any price is at boundary (0/1)
        float_prices = [float(p) for p in prices]
        is_resolved = data.get("closed") or any(p >= 0.999 for p in float_prices)
        if not is_resolved:
            return

        winning = next(
            (outcomes[i] for i, p in enumerate(float_prices) if p >= 0.999), None
        )
        if winning is None:
            return

        won = winning.strip().lower() == entry["outcome_bet"].strip().lower()
        entry["resolved"]  = True
        entry["won"]       = won

        # Calculate payout and net profit
        amount = entry.get("amount", 0)
        price  = entry.get("price_at_bet")
        if won and price and price > 0:
            entry["payout"]     = round(amount / price, 4)
            entry["net_profit"] = round((amount / price) - amount, 4)
        else:
            entry["payout"]     = 0.0
            entry["net_profit"] = round(-amount, 4)

    except Exception:
        pass


def _update_pending(history):
    changed = 0
    for entry in history:
        if not entry.get("resolved"):
            _resolve_entry(entry)
            if entry.get("resolved"):
                changed += 1
    if changed:
        _save(history)
    return history


def _persona_stats(history):
    """Aggregate win/loss and profit per persona across resolved bets."""
    stats = {p: {"wins": 0, "losses": 0, "net_profit": 0.0} for p in PERSONAS}
    stats["Unknown"] = {"wins": 0, "losses": 0, "net_profit": 0.0}

    for entry in history:
        if not entry.get("resolved"):
            continue
        backer = entry.get("primary_backer", "Unknown")
        if backer not in stats:
            stats[backer] = {"wins": 0, "losses": 0, "net_profit": 0.0}

        if entry.get("won"):
            stats[backer]["wins"] += 1
        else:
            stats[backer]["losses"] += 1
        stats[backer]["net_profit"] += entry.get("net_profit") or 0.0

    # Remove personas with no history
    return {k: v for k, v in stats.items() if v["wins"] + v["losses"] > 0}


def get_performance_summary():
    """Return a summary string to inject into the Gemini prompt."""
    history = _update_pending(_load())

    if not history:
        return "No bet history yet — this is the first run."

    resolved = [h for h in history if h.get("resolved")]
    pending  = [h for h in history if not h.get("resolved")]
    wins     = [h for h in resolved if h.get("won")]
    losses   = [h for h in resolved if not h.get("won")]
    win_rate = len(wins) / len(resolved) * 100 if resolved else 0

    total_wagered = sum(h.get("amount", 0) for h in resolved)
    total_profit  = sum(h.get("net_profit") or 0 for h in resolved)

    lines = [
        "=== BOT PERFORMANCE HISTORY ===",
        f"Total bets: {len(history)} | Resolved: {len(resolved)} | Pending: {len(pending)}",
        f"Wins: {len(wins)} | Losses: {len(losses)} | Win Rate: {win_rate:.1f}%",
        f"Total wagered: ${total_wagered:.2f} | Net profit: ${total_profit:+.2f}",
        "",
    ]

    # Strategy leaderboard
    pstats = _persona_stats(history)
    if pstats:
        lines.append("=== STRATEGY LEADERBOARD (ranked by win rate) ===")
        ranked = sorted(
            pstats.items(),
            key=lambda x: (x[1]["wins"] / max(1, x[1]["wins"] + x[1]["losses"])),
            reverse=True,
        )
        for name, s in ranked:
            total = s["wins"] + s["losses"]
            rate  = s["wins"] / total * 100 if total else 0
            if total < 3:
                confidence = "insufficient data"
            elif rate >= 60:
                confidence = "PROVEN — lean into this strategy"
            elif rate >= 40:
                confidence = "NEUTRAL — use with caution"
            else:
                confidence = "UNDERPERFORMING — reduce or avoid"
            lines.append(
                f"  {name:20s} | {s['wins']}W {s['losses']}L ({rate:.0f}%) | net ${s['net_profit']:+.2f} | {confidence}"
            )
        lines += [
            "",
            "STRATEGY SIZING INSTRUCTIONS:",
            "- Proven strategies (>60% win rate, 3+ bets): use full Kelly fraction.",
            "- Neutral strategies (40-60%): apply 0.75x Kelly fraction.",
            "- Underperforming strategies (<40%): apply 0.5x Kelly fraction or skip entirely.",
            "- Prioritize proven strategies when multiple bets compete for the same slot.",
        ]

    # Recent bets
    lines += ["", "Recent bets (last 10):"]
    for h in history[-10:]:
        if h.get("resolved"):
            profit_str = f" | net ${h.get('net_profit', 0):+.2f}"
            icon = "✅ WIN " if h.get("won") else "❌ LOSS"
        else:
            profit_str = ""
            icon = "⏳ PEND"
        backer = h.get("primary_backer", "?")
        lines.append(
            f"  [{icon}] [{backer:12s}] {h['market_question']} → {h['outcome_bet']} ${h['amount']:.2f}{profit_str}"
        )

    lines += [
        "",
        "Use this history to improve strategy. Avoid repeating losing patterns.",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    print(get_performance_summary())
