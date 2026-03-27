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

def analyze_with_gemini(market_data, history_summary="", balance=4.0):
    """
    Sends market data to Gemini for analysis and HTML generation.
    Gemini uses Google Search to research each match and estimate true probability,
    then compares to Polymarket price to find edge.
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

    # ── PROMPT 1: trades only (no HTML, no fluff) ──────────────────────────────
    prompt_trades = f"""
    {history_block}You are an elite Prediction Market Analyst specializing in esports markets (CS2, LoL, Valorant).
    You are an edge-detection engine. Use Google Search to research each match and estimate the TRUE
    probability of each outcome, then compare to the Polymarket price to find mispricing.
    RSI > 70 = Overbought. RSI < 30 = Oversold.

    **CORE RULE**: Only bet when research shows the market price is wrong by >= 7%.
    No edge = no bet. Return an empty array if nothing qualifies — that is a valid answer.
    CS2 markets rarely misprice by more than 15%, so edges of 7–14% are the realistic sweet spot.

    ---
    ## STEP 1 — RESEARCH & EDGE SCAN
    For every market below, use Google Search to find: head-to-head record, recent form
    (last 3–5 matches), roster changes, meta shifts, tournament context.

    For each market:
    A. Estimate TRUE probability from research (ignore market price). Round to 5%.
    B. Rate evidence: HIGH (3+ recent credible sources) | MEDIUM (1-2 or older) | LOW (skip)
    C. Edge = |true_prob − market_price|
    D. Gate: ADVANCE only if evidence >= MEDIUM AND edge >= 0.07 AND price between 0.11–0.88

    ---
    ## STEP 2 — VALIDATION (for each ADVANCED bet)
    - Counter-search: "why [Team] will lose [match]" — credible counter shifts prob >7%? DISCARD.
    - BO1 format? Adjust true_prob down for favorite. Adjusted edge < 0.07? DISCARD.
    - Kelly: f* = edge / (1 − market_price) × (0.30 if HIGH else 0.20). Cap at ${balance * 0.12:.2f}.

    ---
    ## STEP 3 — OUTPUT JSON (your entire response must be ONLY this, nothing else)
    Output ONLY the JSON array below. No explanation, no HTML, no markdown.

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
        "strategy": "Form Edge",
        "primary_backer": "Form Edge",
        "rationale": "T1 8-match win streak, market slow to update"
      }}
    ]
    </JSON_DATA>

    If nothing qualifies: <JSON_DATA>[]</JSON_DATA>

    "strategy" and "primary_backer": same value from:
      "Form Edge" | "Mispriced Favorite" | "Underdog Value" | "Momentum" | "Contrarian" | "Information Edge"
    "outcome": EXACT string from market data. "bucket": "core" or "satellite".
    Core: market_price 0.55–0.88, target 5–9 bets, max ${balance * 0.12:.2f} each, 85% of fund.
    Satellite: market_price 0.11–0.40, target 2–3 bets, 15% of fund.
    One bet per match. Category cap: max 35% per game (cs2/lol/valorant).
    Total must equal exactly ${balance:.2f}.

    Data:
    {json.dumps(optimized_data, indent=2)}
    """

    # ── PROMPT 2: HTML report (uses trade decisions from call 1) ────────────────
    def build_html_prompt(trades, data):
        trades_summary = json.dumps(trades, indent=2) if trades else "[]"
        return f"""
    You are generating an esports prediction market analysis report in HTML.
    Color palette: Background #000000 | Accent #53277D | Secondary #00FFDD | Highlight #FFB300 | Text #FCFCFC
    Return ONLY valid HTML starting with <!DOCTYPE html>. No markdown.

    The trading engine already made these decisions (DO NOT change them):
    {trades_summary}

    Generate a report with these sections:

    ### Section 1 — Market Overview
    Table per category (cs2 / valorant / league-of-legends):
    | Resolves | Match | Volume | Market Price | RSI | Sentiment (0-100) | Controversy (0-10) | Key Finding |
    Use the data below. Format Resolves as "Mar 09 18:00 UTC".

    ### Section 2 — Edge Analysis
    For each market, show: True Prob (from trades if bet, otherwise your estimate) | Market Price | Edge | Evidence | Decision (BET/SKIP) | Reason

    ### Section 3 — Final Portfolio
    Table of all bets from the trades above:
    | Bucket | Match | Outcome | Strategy | Resolves | True Prob | Market Price | Edge | Stake |
    Core total | Satellite total | Grand total

    ### Section 4 — Projected Returns
    | Match | Outcome | Stake | Payout if Win | Net Profit | Win Prob | Expected Value |
    EV = (true_prob × net_profit) − ((1 − true_prob) × stake)
    Show: Best Case | EV-Weighted Return | Total EV

    Market data:
    {json.dumps(data, indent=2)}
    """

    def _call_gemini(client, prompt_text, config, label):
        """Helper: call Gemini with retries, return raw text or empty string."""
        response = None
        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt_text,
                    config=config,
                )
                break
            except Exception as e:
                if "429" in str(e):
                    print(f"\n⚠️ API Quota Hit ({label}). Waiting 10s... (Attempt {attempt}/3)")
                    time.sleep(10)
                else:
                    raise e

        if not response:
            print(f"Error: No response from Gemini ({label}) after retries.")
            return ""

        raw = response.text
        if not raw:
            try:
                parts = response.candidates[0].content.parts
                raw = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
            except Exception:
                raw = ""

        if not raw:
            for retry in range(2, 4):
                print(f"⚠️ Gemini returned empty response ({label}). Retrying ({retry}/3)...")
                time.sleep(5)
                try:
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt_text,
                        config=config,
                    )
                    raw = response.text
                    if not raw:
                        try:
                            parts = response.candidates[0].content.parts
                            raw = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
                        except Exception:
                            raw = ""
                    if raw:
                        break
                except Exception as e:
                    print(f"  Retry error: {e}")

        return raw or ""

    try:
        search_tool = types.Tool(google_search=types.GoogleSearch())

        # ── CALL 1: Trades only (Google Search + JSON output) ───────────────────
        trades_config = types.GenerateContentConfig(
            tools=[search_tool],
            max_output_tokens=12000,
        )
        print("\n[1/2] Researching markets and selecting trades...")
        trades_raw = _call_gemini(client, prompt_trades, trades_config, "trades")

        if not trades_raw:
            print("Error: Gemini returned an empty trades response after 3 attempts.")
            return [], ""

        # Extract JSON portfolio — try tagged block first, then bare array
        portfolio_data = []
        json_match = re.search(r'<JSON_DATA>(.*?)</JSON_DATA>', trades_raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1).strip()
            raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
        else:
            # Gemini often drops the XML tags — grab the first JSON array in the response
            bare = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```|(\[[\s\S]*?\])', trades_raw)
            raw = (bare.group(1) or bare.group(2)).strip() if bare else ""

        if raw:
            try:
                portfolio_data = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"Error parsing AI portfolio JSON: {e}")
                print(f"Raw snippet:\n{raw[:300]}")

        if not portfolio_data:
            print("⚠️ Gemini returned empty portfolio [] — edge gate too strict or no mispriced markets today.")
        else:
            print(f"  Gemini selected {len(portfolio_data)} bet(s):")
            for b in portfolio_data:
                print(f"    {b.get('outcome','?'):15s} | edge={b.get('edge','?')} | ev={b.get('evidence_quality','?')} | ${b.get('amount','?')} | {b.get('market_question','')[:45]}")

        # ── CALL 2: HTML report (large token budget, no research needed) ────────
        html_config = types.GenerateContentConfig(
            max_output_tokens=32000,
        )
        print("\n[2/2] Generating HTML report...")
        html_raw = _call_gemini(client, build_html_prompt(portfolio_data, optimized_data), html_config, "html")

        html_content = html_raw.replace("```html", "").replace("```", "") if html_raw else "<html><body><p>Report generation failed.</p></body></html>"

        print("\n--- AI ANALYSIS COMPLETE ---\n")

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