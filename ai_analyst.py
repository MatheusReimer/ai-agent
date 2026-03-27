import os
import sys
import json
import webbrowser
import re
import warnings
import time
warnings.filterwarnings("ignore", category=FutureWarning)

# Try to import the new SDK, provide instructions if missing
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

from config import GEMINI_API_KEY, HTML_FILENAME

def analyze_with_gemini(market_data, history_summary="", balance=4.0, arb_markets=None):
    """
    Sends market data to Gemini for analysis and HTML generation.

    Args:
        market_data:    raw Polymarket markets (used for LLM-inference fallback)
        history_summary: historical win/loss context string
        balance:        available fund in USD
        arb_markets:    pre-matched sportsbook arb opportunities from market_matcher.
                        When provided, these are treated as the primary bet source —
                        sportsbook probability IS the true probability, no LLM inference needed.
    """
    if not genai:
        print("Error: The 'google-genai' library is missing.")
        print("Please run: pip install google-genai")
        return [], ""

    if not GEMINI_API_KEY:
        print("Please set your GEMINI_API_KEY environment variable.")
        return [], ""

    print("Sending data to Gemini (New SDK) for analysis...")
    
    # Initialize the new Client
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Optimize data: Remove raw 'price_history' to save tokens
    print("Optimizing data payload size...")
    MIN_SHARES = 5
    optimized_data = []
    skipped_resolved = 0
    now = time.time()
    for m in market_data:
        try:
            import datetime
            primary = m.get("markets", [{}])[0]
            outcomes = json.loads(primary["outcomes"]) if isinstance(primary.get("outcomes"), str) else primary.get("outcomes", [])
            prices   = json.loads(primary["outcomePrices"]) if isinstance(primary.get("outcomePrices"), str) else primary.get("outcomePrices", [])
            float_prices = [float(p) for p in prices]

            if any(p <= 0.001 or p >= 0.999 for p in float_prices):
                skipped_resolved += 1
                continue

            # Skip markets where all bettable outcomes are heavy favorites (>90%) — no value
            if all(p >= 0.90 or p <= 0.10 for p in float_prices):
                skipped_resolved += 1
                continue

            # Skip markets that have already started (< 1 hour remaining)
            # Note: esports matches are often scheduled 24-48h out so we can't use the
            # 48h rule recommended for general prediction markets — it kills everything.
            end_date_str = m.get("endDate", "")
            if end_date_str:
                try:
                    end_dt = datetime.datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    hours_left = (end_dt.timestamp() - now) / 3600
                    if hours_left < 1:
                        skipped_resolved += 1
                        continue
                except Exception:
                    pass

            # Use fill_price (5% above market, capped at 0.97) to match actual execution cost
            min_bets = {o: round(MIN_SHARES * min(float(p) * 1.05, 0.97), 2) for o, p in zip(outcomes, prices)}
        except Exception:
            outcomes, float_prices, min_bets = [], [], {}

        ta = m.get("technical_analysis", {})

        # Only send fields Gemini actually needs — strips ~80% of payload size
        optimized_data.append({
            "title":    m.get("title"),
            "category": m.get("category"),
            "endDate":  m.get("endDate"),
            "question": primary.get("question"),
            "outcomes": outcomes,
            "prices":   float_prices,
            "volume":   primary.get("volume") or m.get("volume"),
            "rsi":      ta.get("rsi"),
            "volatility": ta.get("volatility"),
            "min_bets": min_bets,
        })
    if skipped_resolved:
        print(f"  Filtered out {skipped_resolved} already-resolved markets before sending to Gemini.")
    print(f"  Sending {len(optimized_data)} markets to Gemini ({len(json.dumps(optimized_data))//1000}KB payload).")

    history_block = f"""
### BOT PERFORMANCE CONTEXT (Read Before Analyzing)
Use this to calibrate your confidence — avoid repeating patterns that have historically lost.

{history_summary}

---
""" if history_summary else ""

    # Build the arb section of the prompt if sportsbook data is available
    arb_block = ""
    if arb_markets:
        arb_block = f"""
    ---
    ## SPORTSBOOK ARB DATA (Primary Signal — Higher Priority Than LLM Inference)
    The following markets have been matched to sharp sportsbook lines (Pinnacle/Betfair).
    The sportsbook probability IS the true probability — these books have quant teams and
    real-time feeds. Your job is NOT to re-estimate probability here. Use what's given.

    Edge = sportsbook_prob − polymarket_price. Positive edge = Polymarket is underpricing this outcome.
    Only bets with edge >= 0.08 AND polymarket_price between 0.06 and 0.93 are included below.

    {json.dumps(arb_markets, indent=2)}

    **ARB BET RULES:**
    - Use sportsbook_prob directly as true_prob in the JSON output
    - Classify strategy as "Sportsbook Arb" for all arb bets
    - Kelly: f* = (sportsbook_prob − polymarket_price) / (1 − polymarket_price), apply 0.35x fraction
    - Minimum edge for a Core arb bet: 0.08 | Minimum for Satellite arb: 0.12 (higher payout needed)
    - DISCARD if match_confidence < 0.70 (team name match uncertain)
    - DISCARD if bookmaker lag is likely gone (high RSI already moved to match sportsbook line)
    ---
"""

    prompt = f"""
    {history_block}You are an elite Prediction Market Analyst.
    You analyze both esports and sports markets on Polymarket.
    Your primary edge source is sportsbook arbitrage: sharp books (Pinnacle, Betfair) are better
    probability estimators than any LLM. When sportsbook data is available, use it. No guessing.
    RSI > 70 = Overbought. RSI < 30 = Oversold.

    **CORE RULE**: A bet only exists when there is a measurable, data-backed edge.
    No edge = no bet. Capital preservation on low-edge days beats forced trades.

    **STYLING**: Background #000000 | Accent #53277D | Secondary #00FFDD | Highlight #FFB300 | Text #FCFCFC
    Dark-themed CSS. Return ONLY valid HTML — no markdown code blocks.

    {arb_block}
    ---
    ## STEP 1 — MANDATORY: JSON OUTPUT (output this BEFORE any HTML)
    The trading engine reads this first. Output ALL final bets (arb + LLM) here:

    <JSON_DATA>
    [
      {{
        "market_question": "exact question from data",
        "outcome": "exact outcome string (e.g. T1, Yes, Cloud9)",
        "amount": 1.50,
        "bucket": "core",
        "true_prob": 0.72,
        "market_price": 0.55,
        "edge": 0.17,
        "evidence_quality": "HIGH",
        "strategy": "Sportsbook Arb",
        "primary_backer": "Sportsbook Arb",
        "rationale": "Pinnacle: 72% | Polymarket: 55% | Edge: +17% | Bookmaker: Pinnacle"
      }}
    ]
    </JSON_DATA>

    If NO bets pass all filters: <JSON_DATA>[]</JSON_DATA>

    "strategy" and "primary_backer" must be the SAME value, chosen from:
      "Sportsbook Arb" | "Form Edge" | "Mispriced Favorite" | "Underdog Value" | "Momentum" | "Contrarian" | "Information Edge"
    Prefer "Sportsbook Arb" for any bet sourced from the arb data above.
    "outcome" must be the EXACT string from the market data.
    After the JSON block, write the full HTML report starting with <!DOCTYPE html>.

    ---
    ## STEP 2 — ARB OVERVIEW (HTML Section 1)
    If sportsbook arb data was provided, show a table of all arb opportunities found:
    | Sport | Match | Outcome | Sportsbook Prob | Polymarket Price | Edge | Bookmaker | Match Confidence | Decision |
    Mark each as: ✅ BET (edge >= threshold, confidence >= 0.70) or ❌ SKIP (reason).
    Show a count: "X arb opportunities found, Y meet threshold."

    ---
    ## STEP 3 — LLM MARKET OVERVIEW (HTML Section 2)
    For markets WITHOUT sportsbook data (the unmatched ones in the raw data below),
    use Google Search to find recent news, match results, roster changes, patch notes.
    Output a table:
    | Resolves | Match | Sport/Category | Volume | Market Price | RSI | Sentiment (0-100) | Key Finding |
    Format Resolves as "Mar 09 18:00 UTC".

    ---
    ## STEP 4 — LLM EDGE SCANNING (HTML Section 3) — for unmatched markets only
    For each unmatched market (no sportsbook line available), run the edge pipeline.
    Skip this section entirely if all markets were matched to sportsbook data.

    **4A. Research** (Google Search): head-to-head record, recent form (last 3–5 matches),
    roster changes, meta shifts, tournament context, analyst predictions.

    **4B. Evidence quality**:
    - HIGH: 3+ credible recent sources, confident ±5%
    - MEDIUM: 1–2 sources or mixed signals, confident ±15%
    - LOW: thin/speculative → SKIP immediately

    **4C. Estimate TRUE probability** from research only (ignore market price). Round to 5%.

    **4D. Edge** = |true_prob − market_price|. Classify strategy type:
    "Form Edge" | "Mispriced Favorite" | "Underdog Value" | "Momentum" | "Contrarian" | "Information Edge"

    **4E. Gate** — ADVANCE only if: evidence >= MEDIUM AND edge >= 0.15 AND price in (0.11, 0.88)

    Output table:
    | Match | Outcome | True Prob | Market Price | Edge | Evidence | Strategy | Decision |

    ---
    ## STEP 5 — VALIDATION CHECKLIST (HTML Section 4)
    For every ADVANCED bet (both arb and LLM), run these checks. One FAIL = DISCARD.

    **Check 1 — Counter-research** (Google Search):
    Search "why [Team] will lose [match]", "[Team] weaknesses [tournament]"
    → Strong credible counter shifts true_prob > 10%? → DISCARD.

    **Check 2 — RSI overextension**:
    RSI > 78 AND edge < 0.15? → Market may already reflect sportsbook line → DISCARD.

    **Check 3 — Contextual risk**:
    BO1 format (upsets far more likely than BO3)? Travel disadvantage? Internal team issues?
    → Adjust true_prob. If adjusted edge < threshold → DISCARD.

    **Check 4 — Kelly sizing**:
    Arb bets: f* = edge / (1 − market_price) × 0.35
    LLM bets: f* = edge / (1 − market_price) × (0.30 if HIGH else 0.20)
    → Stake = f* × ${balance:.2f}. Cap at ${balance * 0.12:.2f}. Below min_bet? → SKIP.

    Output table:
    | Match | Outcome | Source | Check 1 | Check 2 | Check 3 | Check 4 Stake | Final |

    ---
    ## STEP 6 — FINAL PORTFOLIO (HTML Section 5) — ${balance:.2f} Fund
    Allocate exactly ${balance:.2f} across all bets that passed Step 5.

    **CORE BUCKET (85% = ${balance * 0.85:.2f})**: edge bets with market_price 0.50–0.90
    - Arb bets: edge >= 0.08 | LLM bets: edge >= 0.15, evidence HIGH/MEDIUM
    - No single bet > 12% of fund (${balance * 0.12:.2f})
    - Target 5–10 bets

    **SATELLITE BUCKET (15% = ${balance * 0.15:.2f})**: underdogs with market_price 0.10–0.45
    - Arb bets: edge >= 0.12 | LLM bets: edge >= 0.15, evidence MEDIUM+
    - Target 2–3 bets

    **RULES:**
    - One bet per match. No exceptions.
    - SPORT/CATEGORY CAP: max 35% (${balance * 0.35:.2f}) in any single sport or category
    - Respect min_bets field
    - Fewer than 3 total bets passing? Output empty portfolio — do NOT force trades

    Output table:
    | Bucket | Source | Match | Outcome | Strategy | Resolves | True Prob | Market Price | Edge | Stake |
    Summary: Core = $X.XX | Satellite = $X.XX | Total = ${balance:.2f}

    ---
    ## STEP 7 — PROJECTED RETURNS (HTML Section 6)
    | Bucket | Source | Match | Outcome | Stake | Payout if Win | Net Profit | Win Prob | EV |
    EV = (true_prob × net_profit) − ((1 − true_prob) × stake)
    Totals: Best Case (all win) | EV-Weighted Return | Total EV

    ---
    LLM Fallback Market Data (unmatched markets — use Google Search to evaluate):
    {json.dumps(optimized_data, indent=2)}
    """

    try:
        # Enable Google Search for live data retrieval
        response = None
        
        # Configure the Google Search Tool using the new types
        search_tool = types.Tool(google_search=types.GoogleSearch())
        generate_config = types.GenerateContentConfig(
            tools=[search_tool],
            max_output_tokens=16000,
        )

        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=generate_config
                )
                break
            except Exception as e:
                if "429" in str(e):
                    print(f"\n⚠️ API Quota Hit. Waiting 10s... (Attempt {attempt}/3)")
                    time.sleep(10)
                else:
                    raise e
        
        if not response:
            print("Error: Failed to get response from Gemini after retries.")
            return [], ""

        print("\n--- AI ANALYSIS COMPLETE ---\n")

        # Safely extract text — response.text can be None when Google Search tool is used
        raw_text = response.text
        if not raw_text:
            try:
                parts = response.candidates[0].content.parts
                raw_text = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
            except Exception:
                raw_text = ""
        if not raw_text:
            for retry in range(2, 4):
                print(f"⚠️ Gemini returned empty response. Retrying ({retry}/3)...")
                time.sleep(5)
                try:
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config=generate_config
                    )
                    raw_text = response.text
                    if not raw_text:
                        try:
                            parts = response.candidates[0].content.parts
                            raw_text = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
                        except Exception:
                            raw_text = ""
                    if raw_text:
                        break
                except Exception as e:
                    print(f"  Retry error: {e}")

        if not raw_text:
            print("Error: Gemini returned an empty response after 3 attempts.")
            return [], ""

        # Extract JSON from raw response BEFORE any cleanup
        portfolio_data = []
        json_match = re.search(r'<JSON_DATA>(.*?)</JSON_DATA>', raw_text, re.DOTALL)

        # Clean up potential markdown code blocks
        html_content = raw_text.replace("```html", "").replace("```", "")
        if json_match:
            try:
                # Strip markdown code fences Gemini sometimes wraps around the JSON
                raw = json_match.group(1).strip()
                raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
                portfolio_data = json.loads(raw)
                html_content = html_content.replace(json_match.group(0), "")
            except json.JSONDecodeError as e:
                print(f"Error parsing AI portfolio JSON: {e}")
                print(f"Raw JSON received:\n{json_match.group(1)[:300]}")
        else:
            print("⚠️ No <JSON_DATA> block found in AI response — no trades to execute.")
        
        # Write the latest report for browser preview (not archived yet)
        with open(HTML_FILENAME, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"Report preview saved to {HTML_FILENAME}.")
        if sys.stdout.isatty():  # only open browser in interactive sessions
            webbrowser.open("file://" + os.path.abspath(HTML_FILENAME))

        return portfolio_data, html_content
        
    except Exception as e:
        print(f"\nError communicating with Gemini: {e}")
        return [], ""