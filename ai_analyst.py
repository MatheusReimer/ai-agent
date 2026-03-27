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

            # Skip markets resolving in less than 48 hours — endgame volatility, thin liquidity, info already priced in
            end_date_str = m.get("endDate", "")
            if end_date_str:
                try:
                    end_dt = datetime.datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    hours_left = (end_dt.timestamp() - now) / 3600
                    if hours_left < 48:
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

    prompt = f"""
    {history_block}You are an elite Prediction Market Analyst specializing in esports markets.
    You are an edge-detection engine — not an opinion generator.
    A bet only exists when research-backed TRUE probability diverges meaningfully from market price.
    If no clear edge exists today, the correct answer is NO BETS. Capital preservation beats forced trades.
    RSI > 70 = Overbought. RSI < 30 = Oversold.

    **STYLING**: Background #000000 | Accent #53277D | Secondary #00FFDD | Highlight #FFB300 | Text #FCFCFC
    Dark-themed CSS. Return ONLY valid HTML — no markdown code blocks.

    ---
    ## STEP 1 — MANDATORY: JSON OUTPUT (output this BEFORE any HTML)
    The trading engine reads this first. After completing all research steps below, output trades here:

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
        "rationale": "T1 on 8-match win streak, market slow to update after roster change"
      }}
    ]
    </JSON_DATA>

    If NO bets pass all filters: <JSON_DATA>[]</JSON_DATA>

    "strategy" and "primary_backer" must be the SAME value, chosen from:
      "Form Edge" | "Mispriced Favorite" | "Underdog Value" | "Momentum" | "Contrarian" | "Information Edge"
    "outcome" must be the EXACT string from the market data.
    After the JSON block, write the full HTML report starting with <!DOCTYPE html>.

    ---
    ## STEP 2 — MARKET OVERVIEW (HTML Section 1)
    For each game category in the data (cs2, valorant, league-of-legends, dota-2):
    Use Google Search to find: recent match results, roster changes, patch notes, tournament standings.
    Output a table per category:
    | Resolves | Match | Volume | Market Price | RSI | Sentiment (0-100) | Controversy (0-10) | Key Finding |
    Sentiment: 0=Very Bearish, 100=Very Bullish. Controversy: 0=clear consensus, 10=sharp disagreement.
    Format Resolves as "Mar 09 18:00 UTC".

    ---
    ## STEP 3 — EDGE SCANNING (HTML Section 2) — THE CRITICAL GATE
    For every market, run this pipeline. A market only advances if it passes ALL checks.

    **3A. Research** (use Google Search for each match):
    - Head-to-head record (last 6 months)
    - Recent form: last 3–5 match results, map win rates
    - Roster changes, stand-ins, bootcamp news
    - Meta shifts (recent patch impact on team playstyle)
    - Tournament context (bracket pressure, travel schedule, prize pool stakes)
    - Any credible analyst predictions or community consensus

    **3B. Assign Evidence Quality**:
    - HIGH: 3+ credible, recent (< 2 weeks), consistent sources. Estimate ±5% confident.
    - MEDIUM: 1–2 sources, or mixed signals, or data > 2 weeks old. Estimate ±15% confident.
    - LOW: No recent data, pure speculation, conflicting info → SKIP immediately, do not proceed.

    **3C. Estimate TRUE probability** — based solely on your research, ignoring the market price.
    State your reasoning explicitly. Round to nearest 5%.

    **3D. Compute edge** = |true_prob − market_price|

    **3E. Classify strategy type** (what is the source of the edge?):
    - "Form Edge": team's recent form not yet reflected in market
    - "Mispriced Favorite": solid team undervalued, market underconfident
    - "Underdog Value": genuine upset potential, payout justifies risk
    - "Momentum": strong RSI trend with confirmed external cause
    - "Contrarian": market overreacted to recent bad news, overcorrected
    - "Information Edge": credible roster/bootcamp/lineup info market hasn't priced in

    **3F. Apply the gate** — ADVANCE only if ALL of the following are true:
    ✅ evidence_quality is HIGH or MEDIUM
    ✅ edge >= 0.15 (15 percentage points)
    ✅ market_price is between 0.11 and 0.88
    ✅ There IS a clear, articulable reason the market is wrong (not just "feels like it")
    Otherwise: SKIP. Record the reason.

    Output table:
    | Match | Outcome | True Prob | Market Price | Edge | Evidence | Strategy | Decision | Reason |

    ---
    ## STEP 4 — VALIDATION CHECKLIST (HTML Section 3)
    For each ADVANCED market from Step 3, run every check. A single FAIL = bet is DISCARDED.

    **Check 1 — Counter-research** (Google Search required):
    Search: "[Team] weaknesses", "why [Team] will lose [opponent]", "upset prediction [match]"
    Find the strongest argument AGAINST your position. Is it credible? Does it change your true_prob estimate?
    → If counter-argument is from a credible source and shifts true_prob by > 10% → DISCARD.

    **Check 2 — Source credibility**:
    Where did your key evidence come from? Twitter rumors = low. Official team statements = high. Liquipedia stats = high.
    → If primary evidence source is low credibility → DISCARD or downgrade to LOW evidence → SKIP.

    **Check 3 — RSI overextension**:
    If RSI > 78 for the favored team, the market may already be overbought — price will revert before match.
    → If RSI > 78 AND edge < 0.20 → DISCARD (not enough edge to justify reversal risk).

    **Check 4 — Contextual risk**:
    Is there: a travel schedule disadvantage? A BO1 vs BO3 format difference (upsets more likely in BO1)?
    Any known internal team issues (drama, benching, boot camp skipped)?
    → Flag and reduce true_prob accordingly. If adjusted edge falls below 0.15 → DISCARD.

    **Check 5 — Kelly sanity check**:
    Calculate: f* = (true_prob − market_price) / (1 − market_price)
    Apply fraction: HIGH evidence = 0.30, MEDIUM evidence = 0.20
    Stake = f* × fraction × ${balance:.2f}
    → If calculated stake < min_bets for this market → SKIP (not worth minimum position).
    → If calculated stake > 12% of fund (${balance * 0.12:.2f}) → cap at ${balance * 0.12:.2f}.

    Output table:
    | Match | Check 1 Counter | Check 2 Sources | Check 3 RSI | Check 4 Context | Check 5 Kelly Stake | Final: ✅ KEEP / ❌ DISCARD |

    ---
    ## STEP 5 — FINAL PORTFOLIO (HTML Section 4) — ${balance:.2f} Fund
    Only bets that passed ALL Step 4 checks. Allocate exactly ${balance:.2f}.

    **CORE BUCKET (85% = ${balance * 0.85:.2f})** — mispriced favorites, form edges, momentum plays
    - market_price: 0.55–0.88 | true_prob: 0.60–0.89 | edge >= 0.15 | evidence: HIGH or MEDIUM
    - Target 5–9 bets. No single bet > 12% of fund (${balance * 0.12:.2f}).
    - Strategies: Form Edge, Mispriced Favorite, Momentum, Information Edge

    **SATELLITE BUCKET (15% = ${balance * 0.15:.2f})** — high-payout underdog value
    - market_price: 0.11–0.40 | true_prob: 0.25–0.45 | edge >= 0.15 | evidence: MEDIUM minimum
    - Target 2–3 bets. Sized smaller — one win covers several losses.
    - Strategies: Underdog Value, Contrarian

    **PORTFOLIO RULES:**
    - ONE bet per match maximum — no two positions on the same game
    - CATEGORY CAP: max ${balance * 0.35:.2f} (35%) in any single game (cs2 / valorant / lol / dota2)
    - MINIMUM BET: respect each market's min_bets field — never go below it
    - NO EDGE = NO BET: if fewer than 3 markets survived Steps 3+4, output empty portfolio

    Output table:
    | Bucket | Match | Outcome | Strategy | Resolves | True Prob | Market Price | Edge | Evidence | Stake |
    Summary line: Core = $X.XX | Satellite = $X.XX | Total = ${balance:.2f}

    ---
    ## STEP 6 — PROJECTED RETURNS (HTML Section 5)
    For each portfolio bet:
    | Bucket | Match | Outcome | Stake | Payout if Win | Net Profit | True Win Prob | Expected Value |
    EV = (true_prob × net_profit) − ((1 − true_prob) × stake)
    Show totals: Best Case (all win) | EV-Weighted Realistic Return | Total Portfolio EV

    ---
    Data:
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