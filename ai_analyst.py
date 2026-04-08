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
    for m in market_data:
        try:
            primary = m.get("markets", [{}])[0]
            outcomes = json.loads(primary["outcomes"]) if isinstance(primary.get("outcomes"), str) else primary.get("outcomes", [])
            prices   = json.loads(primary["outcomePrices"]) if isinstance(primary.get("outcomePrices"), str) else primary.get("outcomePrices", [])
            float_prices = [float(p) for p in prices]

            if any(p <= 0.001 or p >= 0.999 for p in float_prices):
                skipped_resolved += 1
                continue

            # Skip heavy favorites — no bettable edge
            if all(p >= 0.90 or p <= 0.10 for p in float_prices):
                skipped_resolved += 1
                continue

            # Skip prop bets — not researchable by Gemini
            q = (primary.get("question") or m.get("title") or "").lower()
            if any(kw in q for kw in ["odd/even", "total kills", "total rounds", "first kill", "first blood", "pistol round"]):
                skipped_resolved += 1
                continue

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
    for i, m in enumerate(optimized_data, 1):
        q = m.get("question") or m.get("title") or "?"
        ends = m.get("endDate", "")[:10]
        prices = m.get("prices", [])
        price_str = " / ".join(f"{p:.0%}" for p in prices) if prices else "?"
        print(f"  {i:2}. [{ends}] {q[:65]} ({price_str})")

    history_block = f"""
### BOT PERFORMANCE CONTEXT (Read Before Analyzing)
Use this to calibrate your confidence — avoid repeating patterns that have historically lost.

{history_summary}

---
""" if history_summary else ""

    prompt = f"""
    {history_block}You are Frodo, the Moderator of an elite Investment Committee for Prediction Markets.
    Your committee consists of 8 distinct analyst personas, plus yourself (The Chairman) as the tie-breaker.
    Review the following raw JSON data from Polymarket.
    Note: The data includes 'rsi' and 'volatility' fields.
    - RSI > 70 is "Overbought" (Expensive). RSI < 30 is "Oversold" (Cheap).

    Your goal is to generate a focused HTML report with TWO sections: the Roundtable debate and the Final Portfolio.
    **CRITICAL**: Use the Google Search tool to fetch real-time data for team stats, recent news, and roster changes — personas must reference actual findings.
    Return ONLY valid HTML code. Do not include markdown code blocks.

    **STYLING INSTRUCTIONS**:
    Use the following color palette strictly:
    - Background: #000000
    - Primary Accent: #53277D
    - Secondary Accent: #00FFDD
    - Highlight: #FFB300
    - Text: #FCFCFC
    Style the HTML with a modern, dark-themed CSS using these colors.
    Make each persona's name appear in their own accent color to make the dialogue easy to follow.

    ### TOURNAMENT TIER RULE (applies to ALL personas)
    Before any persona speaks, look up the tournament on Liquipedia to classify its tier:
    - **S/A-tier** (BLAST Premier, ESL Pro League, IEM, PGL Major, VALORANT Champions/Masters, LoL Worlds/MSI):
      High-profile. Top teams are well-scouted, consistent, and rarely get upset.
      → Prefer the FAVORITE. Underdogs need overwhelming evidence (edge > 20%) to be considered.
    - **B-tier** (Regional leagues, ESL Challenger, VCT Challengers, LEC/LCS/LCK regular season):
      Moderate predictability. Judge on pure edge — either side is fair game.
    - **C/D-tier** (small online cups, unknown organizers, semi-pro, amateur):
      Highly chaotic. Teams have stand-ins, low motivation, inconsistent prep.
      → Prefer the UNDERDOG (price 0.11–0.45). Skip heavy favorites — variance is too high to trust them.

    ### SECTION 1: The Roundtable Discussion
    Simulate a lively, opinionated debate among these 8 personas about the markets above.
    Write it as a dialogue — personas interrupt, argue, and challenge each other in character.
    Each persona speaks in their own voice and references real search findings where relevant.

    1. **"Safe Hands" Gimliwise Gamgee** (Conservative): Dislikes high volatility. Only likes >75% odds. In S/A-tier he trusts favorites fully; in C/D-tier he skips entirely — too risky.
    2. **"YOLO" Peregrin Took** (High Risk): Loves long shots (<30% odds). In C/D-tier he's excited — upsets are common there. In S/A-tier he only backs underdogs if edge > 20%.
    3. **"Value" Aragorn** (Value Investor): Looks for mispriced odds. Tier affects how he adjusts "true probability" — he gives favorites a bigger edge buffer in S/A, shrinks it in C/D.
    4. **"Trend" Legolas** (Momentum): Loves high RSI (strong uptrend). In S/A-tier form streaks are more reliable; in C/D-tier he's skeptical of streaks — random variance is high.
    5. **"Skeptic" Gimli** (Contrarian): Bets against the crowd. In C/D-tier he loves fading the favorite — public money is dumb money on small events.
    6. **"Quant" Gandalf** (Data): Focuses on RSI and Volatility. Notes that C/D-tier markets have high volatility by nature — adjusts Kelly fraction down accordingly.
    7. **"Insider" Boromir** (News/Leaks): Checks for roster issues, bootcamp results, coach changes. More impactful in C/D-tier where a single stand-in can flip the match.
    8. **"Macro" Elrond** (Big Picture): Tournament stakes matter — S/A teams play harder (Major points, prize money). C/D teams may not be fully motivated.

    Each persona must:
    - Cite the tournament tier and explain how it shapes their view.
    - Reference actual search results (team form, roster news, etc.).
    - Argue or agree with others — make it feel like a real heated debate.
    - Highlight conflicts (e.g., Peregrin Took wants a C/D underdog, Gimliwise Gamgee refuses to touch it).

    If there is a tie or lack of consensus, **Frodo** (The Chairman) enters to make the final call.

    ### SECTION 2: Final Consensus Portfolio (${balance:.2f} Fund)
    Based on the Roundtable's conclusions, allocate exactly ${balance:.2f}.
    **Strategy**: Diversified Fractional Kelly.
    1. **Spread Across Markets**: Target 10–15 bets across DIFFERENT matches and categories. Never put more than 10% of the fund into a single bet.
    2. **Fractional Kelly**: Use 25–40% of the full Kelly-suggested size per bet.
    3. **Consensus**: Only invest if at least 2 personas agreed (or Chairman overruled). For markets where only 1 persona is positive but there's no strong opposition, allocate a small exploratory bet ($2–$3).
    4. **CRITICAL — MINIMUM BET**: Each market has a "min_bets" field showing the EXACT minimum dollar amount per outcome. You MUST allocate AT LEAST that amount for the chosen outcome, or skip the bet entirely.

    Output as a table:
    | Market | Resolves | Outcome | Allocation | Primary Backer | Rationale |
    (Format endDate as "Mar 09 18:00 UTC". Ensure allocations sum to exactly ${balance:.2f}.)

    ### MACHINE-READABLE OUTPUT
    **CRITICAL FINAL STEP**: After the closing </html> tag, output ONLY the raw JSON below.
    Do NOT wrap it in HTML. Do NOT skip this step. The trading engine will fail without it.
    The "primary_backer" must be EXACTLY one of: Safe Hands, YOLO, Value, Trend, Skeptic, Quant, Insider, Macro, Chairman.
    The "outcome" must be the EXACT outcome string as it appears in the market data (e.g. "Yes", "No", "Over", "T1", "Cloud9").

    </html>
    <JSON_DATA>
    [
      {{"market_question": "exact market question from data", "outcome": "exact outcome string", "amount": 0.40, "rationale": "reason", "primary_backer": "Quant"}},
      {{"market_question": "exact market question from data", "outcome": "exact outcome string", "amount": 0.10, "rationale": "reason", "primary_backer": "Trend"}}
    ]
    </JSON_DATA>

    Data:
    {json.dumps(optimized_data, indent=2)}
    """

    max_503_retries = 5
    for _503_attempt in range(1, max_503_retries + 1):
      try:
        # Enable Google Search for live data retrieval
        response = None

        # Configure the Google Search Tool using the new types
        search_tool = types.Tool(google_search=types.GoogleSearch())
        generate_config = types.GenerateContentConfig(tools=[search_tool])

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

        # Extract JSON — tagged block preferred, bare array fallback
        portfolio_data = []
        json_match = re.search(r'<JSON_DATA>(.*?)</JSON_DATA>', raw_text, re.DOTALL)
        if json_match:
            raw = json_match.group(1).strip()
            raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
        else:
            bare = re.search(r'```(?:json)?\s*(\[.*?\])\s*```|(\[.*?\])', raw_text, re.DOTALL)
            raw = (bare.group(1) or bare.group(2)).strip() if bare else ""

        if raw:
            # Strip Gemini citation tags — [cite: 1, 2\n3] embeds newlines that break JSON
            raw = re.sub(r'\s*\[cite:[^\]]*\]', '', raw, flags=re.DOTALL)
            try:
                portfolio_data = json.loads(raw)
            except json.JSONDecodeError:
                # Salvage complete objects before truncation point
                truncated = re.sub(r',?\s*\{[^{}]*$', '', raw).rstrip(',').strip()
                if not truncated.endswith(']'):
                    truncated += ']'
                try:
                    portfolio_data = json.loads(truncated)
                    print(f"  ⚠️ Response truncated — salvaged {len(portfolio_data)} complete bet(s).")
                except json.JSONDecodeError as e:
                    print(f"Error parsing AI portfolio JSON: {e}")
        else:
            print("⚠️ No JSON found in AI response — no trades to execute.")

        if not portfolio_data:
            print("⚠️ Gemini returned empty portfolio [] — no qualifying bets today.")

        # Clean up markdown from HTML
        html_content = raw_text.replace("```html", "").replace("```", "")
        if json_match:
            html_content = html_content.replace(json_match.group(0), "")
        
        # Write the latest report for browser preview (not archived yet)
        with open(HTML_FILENAME, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"Report preview saved to {HTML_FILENAME}.")
        if sys.stdout.isatty():  # only open browser in interactive sessions
            webbrowser.open("file://" + os.path.abspath(HTML_FILENAME))

        return portfolio_data, html_content

      except Exception as e:
        if "503" in str(e) and _503_attempt < max_503_retries:
            print(f"\nError communicating with Gemini: {e}")
            print(f"⏳ Gemini busy — retrying in 5 min... (attempt {_503_attempt}/{max_503_retries})")
            time.sleep(300)
        else:
            print(f"\nError communicating with Gemini: {e}")
            return [], ""
    return [], ""