"""
Fuzzy-matches Polymarket market outcomes to sportsbook events by team name.

The core challenge: Polymarket uses names like "Fluxo" while a sportsbook might
list "Fluxo Esports". We use token-level similarity to handle abbreviations,
full names, and minor spelling differences.

A match is accepted only if:
  - Similarity score >= 0.65 (tunable)
  - The matched sportsbook event hasn't already been used (1-to-1 matching)
  - The market isn't near-resolved (price between 0.06 and 0.93)
"""

import json
from difflib import SequenceMatcher

MIN_SHARES = 5
SIMILARITY_THRESHOLD = 0.65  # minimum name match confidence


def _similarity(a: str, b: str) -> float:
    """Token-set ratio: robust to word order differences and partial names."""
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())

    # Exact token overlap first (handles "T1" matching "T1" inside "T1 Esports")
    if a_tokens & b_tokens:
        intersection = len(a_tokens & b_tokens)
        union = len(a_tokens | b_tokens)
        token_score = intersection / union
    else:
        token_score = 0.0

    # Fallback: character-level sequence similarity
    seq_score = SequenceMatcher(None, a.lower(), b.lower()).ratio()

    return max(token_score, seq_score)


def _best_match(name: str, candidates: list[str]) -> tuple[str | None, float]:
    """Find the best matching candidate for a given name string."""
    best, score = None, 0.0
    for candidate in candidates:
        s = _similarity(name, candidate)
        if s > score:
            score = s
            best = candidate
    return (best, score) if score >= SIMILARITY_THRESHOLD else (None, 0.0)


def match_markets(polymarket_markets: list, sportsbook_events: list) -> tuple[list, list]:
    """
    Match Polymarket markets to sportsbook events.

    Returns:
        matched:   list of markets with sportsbook oracle data attached (arb candidates)
        unmatched: list of markets with no sportsbook data (fallback to LLM analysis)
    """
    matched = []
    unmatched = []
    used_sb_events = set()  # prevent double-matching the same sportsbook event

    for pm_event in polymarket_markets:
        primary = pm_event.get("markets", [{}])[0]
        outcomes_raw = primary.get("outcomes", "[]")
        prices_raw   = primary.get("outcomePrices", "[]")

        try:
            outcomes     = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
            prices       = json.loads(prices_raw)   if isinstance(prices_raw,   str) else prices_raw
            float_prices = [float(p) for p in prices]
        except Exception:
            unmatched.append(pm_event)
            continue

        title = pm_event.get("title", "")

        # Try to find a sportsbook event that matches this Polymarket market
        # Strategy: find a sportsbook event where at least one team matches an outcome
        best_sb_event   = None
        best_match_score = 0.0
        best_outcome_map = {}  # {pm_outcome: sb_team_name}

        for i, sb_event in enumerate(sportsbook_events):
            if i in used_sb_events:
                continue

            sb_teams = list(sb_event["probabilities"].keys())
            outcome_map = {}
            total_score = 0.0

            for outcome in outcomes:
                team, score = _best_match(outcome, sb_teams)
                if team:
                    outcome_map[outcome] = team
                    total_score += score

            # Accept if at least one outcome matched well
            avg_score = total_score / max(len(outcomes), 1)
            if outcome_map and avg_score > best_match_score:
                best_match_score = avg_score
                best_sb_event    = (i, sb_event)
                best_outcome_map = outcome_map

        if best_sb_event and best_match_score >= SIMILARITY_THRESHOLD:
            sb_idx, sb_event = best_sb_event
            used_sb_events.add(sb_idx)

            # Build per-outcome arb data
            arb_outcomes = []
            for outcome, pm_price in zip(outcomes, float_prices):
                if pm_price <= 0.05 or pm_price >= 0.95:
                    continue  # near-resolved, skip

                sb_team = best_outcome_map.get(outcome)
                if not sb_team:
                    continue

                sb_prob = sb_event["probabilities"][sb_team]
                edge    = round(sb_prob - pm_price, 4)

                arb_outcomes.append({
                    "outcome":        outcome,
                    "polymarket_price": pm_price,
                    "sportsbook_prob":  sb_prob,
                    "edge":             edge,
                    "sb_team_name":     sb_team,
                    "min_bet": round(MIN_SHARES * min(pm_price * 1.05, 0.97), 2),
                })

            if arb_outcomes:
                matched.append({
                    "market_question": primary.get("question", title),
                    "title":           title,
                    "category":        pm_event.get("category", ""),
                    "endDate":         pm_event.get("endDate", ""),
                    "volume":          primary.get("volume") or pm_event.get("volume"),
                    "rsi":             pm_event.get("technical_analysis", {}).get("rsi"),
                    "sport":           sb_event.get("sport", ""),
                    "bookmaker":       sb_event.get("bookmaker", ""),
                    "commence_time":   sb_event.get("commence_time", ""),
                    "match_confidence": round(best_match_score, 2),
                    "outcomes":        arb_outcomes,
                })
            else:
                unmatched.append(pm_event)
        else:
            unmatched.append(pm_event)

    print(f"  Matched {len(matched)} markets to sportsbook odds | {len(unmatched)} unmatched (LLM fallback).")
    return matched, unmatched
