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
    {history_block}You are Frodo, the Moderator of an elite Prediction Market Investment Committee.
    Your committee has 8 analyst personas plus yourself (The Chairman) as tie-breaker.
    You are analyzing esports prediction markets from Polymarket.
    RSI > 70 = Overbought (Expensive). RSI < 30 = Oversold (Cheap).

    **CORE PHILOSOPHY**: You are an edge-detection engine, not an opinion machine. A bet only exists when your research-backed TRUE probability diverges meaningfully from the market price. If no edge exists today, the correct answer is to make NO bets. Preserving capital on low-edge days beats forcing bad trades.

    **STYLING INSTRUCTIONS**:
    - Background: #000000 | Primary Accent: #53277D | Secondary Accent: #00FFDD | Highlight: #FFB300 | Text: #FCFCFC
    - Modern, dark-themed CSS. Return ONLY valid HTML (no markdown code blocks).

    ---
    ## STEP 1 — MANDATORY: JSON OUTPUT (Machine Readable)
    **OUTPUT THIS BEFORE ANY HTML.** The trading engine depends on it appearing first.
    After your research (Steps 2–5 below), output your final trade list between these tags:

    <JSON_DATA>
    [
      {{"market_question": "exact question from data", "outcome": "exact outcome string", "amount": 1.50, "rationale": "edge: our 72% vs market 55%, HIGH evidence", "primary_backer": "Value", "bucket": "core", "true_prob": 0.72, "market_price": 0.55, "edge": 0.17, "evidence_quality": "HIGH"}},
      {{"market_question": "exact question from data", "outcome": "exact outcome string", "amount": 0.80, "rationale": "underdog upset: our 35% vs market 18%, MEDIUM evidence", "primary_backer": "YOLO", "bucket": "satellite", "true_prob": 0.35, "market_price": 0.18, "edge": 0.17, "evidence_quality": "MEDIUM"}}
    ]
    </JSON_DATA>

    If there are NO bets with sufficient edge today, output: <JSON_DATA>[]</JSON_DATA>
    The "primary_backer" must be EXACTLY one of: Safe Hands, YOLO, Value, Trend, Skeptic, Quant, Insider, Macro, Chairman.
    The "outcome" must be the EXACT outcome string from the market data (e.g. "Yes", "No", "T1", "Cloud9").

    After the JSON, write the full HTML report starting with <!DOCTYPE html>.

    ---
    ## STEP 2 — MARKET OVERVIEW (HTML Section 1)
    For each category (league-of-legends, valorant, cs2, dota-2), create a sub-section table:
    | Resolves | Match | Category | Volume | Market Price | RSI | Sentiment (0-100) | Controversy (0-10) | Brief Analysis |

    Use Google Search to find recent news, match history, roster changes, and patch notes for each match.
    Sentiment = 0 (Very Bearish) to 100 (Very Bullish) based on what you find.
    Controversy = 0 (clear consensus) to 10 (experts sharply disagree).
    Format Resolves as "Mar 09 18:00 UTC".

    ---
    ## STEP 3 — EDGE SCANNING (HTML Section 2) ← THE MOST IMPORTANT STEP
    This is the gate that determines what gets bet. For every market in the data:

    **A. Research**: Use Google Search to find team stats, head-to-head records, recent form (last 3-5 matches), coaching changes, bootcamp results, meta shifts, and any relevant leaks or insider info.

    **B. Estimate TRUE probability**: Based purely on your research (not the market price), what is the real probability of each outcome? Be honest — if your research is thin, admit it.

    **C. Compute edge**: `edge = |your_true_prob - market_price|`

    **D. Rate evidence quality**:
    - **HIGH**: Multiple credible sources, recent head-to-head data, strong track record signal. Confident in estimate ±5%.
    - **MEDIUM**: Some data, mixed signals, or sources with lower credibility. Confident ±10-15%.
    - **LOW**: Thin data, no recent matches, pure speculation. Do NOT bet — you have no edge, just noise.

    **E. Apply the gate**: A market advances to portfolio consideration ONLY if:
    - `edge >= 0.15` (15 percentage points minimum divergence from market price)
    - `evidence_quality >= MEDIUM`
    - Market price is between 0.10 and 0.89 (no heavy favorites, no extreme longshots)
    - **If it fails ANY of these, it is SKIPPED. No exceptions.**

    Output this section as a table:
    | Market | Your True Prob | Market Price | Edge | Evidence Quality | Decision (ADVANCE / SKIP) | Skip Reason |

    ---
    ## STEP 4 — ROUNDTABLE (HTML Section 3)
    Only debate markets that ADVANCED from Step 3. Do NOT discuss skipped markets.
    Personas debate only the shortlisted opportunities:
    1. **"Safe Hands" Gimliwise Gamgee** (Conservative): Accepts only HIGH evidence bets with edge >= 0.20. Pushes back on MEDIUM evidence.
    2. **"YOLO" Peregrin Took** (High Risk): Advocates for satellite bets (true_prob 0.25-0.40, underdog value). Checks: is the payout worth it?
    3. **"Value" Aragorn** (Value Investor): Validates the edge calculation. Asks: "Is this market genuinely mispriced, or are we missing something?"
    4. **"Trend" Legolas** (Momentum): Checks RSI. If RSI > 75 on a team the market already favors, warns of reversal risk.
    5. **"Skeptic" Gimli** (Contrarian): For each bet, plays devil's advocate. What is the strongest reason this bet FAILS?
    6. **"Quant" Gandalf** (Data): Runs fractional Kelly calculation live: `f* = (true_prob - market_price) / (1 - market_price)`, then applies 0.25x fraction for MEDIUM, 0.30x for HIGH evidence.
    7. **"Insider" Boromir** (News/Leaks): Evaluates source credibility of the research. Flags if a key piece of info came from a low-credibility source.
    8. **"Macro" Elrond** (Big Picture): Considers meta patches, tournament format, bracket pressure, roster fatigue.

    **Conflict rule**: If Skeptic or Safe Hands raises a counter-argument that nobody can refute → that bet is DISCARDED regardless of edge.
    Chairman breaks ties only. Chairman can also veto a bet if overall confidence feels low.

    ---
    ## STEP 5 — DEVIL'S ADVOCATE (HTML Section 3.5)
    For EVERY bet that survives the Roundtable (not just the top 2), use Google Search to find:
    - "Why [Team] will lose" / "[Team] weaknesses" / "upset risk [match]"
    - Recent quotes from analysts predicting the opposite outcome
    - Any roster issue, travel fatigue, or meta disadvantage

    Output: strongest counter-argument per bet. If counter-argument is highly credible → DISCARD. Mark each bet as: ✅ Survives / ❌ Discarded.

    ---
    ## STEP 6 — FINAL PORTFOLIO (HTML Section 4) — (${balance:.2f} Fund)
    Allocate exactly ${balance:.2f} using Core/Satellite. Only bets that survived Steps 3, 4, and 5.

    **BUCKET A — CORE (85% = ${balance * 0.85:.2f}): High-confidence, mispriced favorites**
    - true_prob: 0.55–0.89 | edge >= 0.15 | evidence_quality: HIGH or MEDIUM
    - Personas: Safe Hands, Value, Quant, Trend, Chairman
    - Target 6–9 bets. No single Core bet > 12% of total fund (${balance * 0.12:.2f}).
    - Kelly sizing: HIGH evidence → 30% Kelly fraction | MEDIUM evidence → 20% Kelly fraction
    - Formula: `stake = (edge / (1 - market_price)) * kelly_fraction * ${balance:.2f}`

    **BUCKET B — SATELLITE (15% = ${balance * 0.15:.2f}): Underdog longshots with real edge**
    - true_prob: 0.25–0.45 | market_price: 0.10–0.40 | edge >= 0.15 | evidence_quality: MEDIUM+
    - Personas: YOLO, Insider, Skeptic (contrarian), Macro
    - Target 2–3 bets. These WILL lose often — one hit pays for several misses.
    - Kelly sizing: Always 15% Kelly fraction (higher uncertainty on longshots).

    **HARD RULES (apply to both buckets):**
    - **NO TWO BETS ON THE SAME MATCH** — one match, one position.
    - **CATEGORY CAP**: No more than 35% of the total fund (${balance * 0.35:.2f}) in a single game category (cs2, valorant, lol, dota2). Diversify across games.
    - **MINIMUM BET**: Each market has a "min_bets" field. Never allocate less than that amount.
    - **SKIP if no edge**: If fewer than 3 markets cleared Step 3, output an empty portfolio. Do NOT force bets.

    Output a table:
    | Bucket | Market | Outcome | Resolves | True Prob | Market Price | Edge | Evidence | Kelly Stake | Primary Backer |
    Then: Core total = ~${balance * 0.85:.2f} | Satellite total = ~${balance * 0.15:.2f} | Grand total = ${balance:.2f}

    ---
    ## STEP 7 — PROJECTED RETURNS (HTML Section 5)
    For each final bet:
    | Bucket | Market | Outcome | Resolves | Stake | Payout if Win | Net Profit | Win Prob (your estimate) | Expected Value |
    Expected Value = (true_prob * net_profit) - ((1 - true_prob) * stake)
    Show: Best Case (all win), Realistic Case (weighted by true_prob), Expected Value sum across portfolio.

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