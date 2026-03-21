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
    {history_block}You are Frodo, the Moderator of an elite Investment Committee for Prediction Markets.
    Your committee consists of 8 distinct analyst personas, plus yourself (The Chairman) as the tie-breaker.
    Review the following raw JSON data from Polymarket.
    Note: The data now includes 'technical_analysis' with RSI and Volatility.
    - RSI > 70 is "Overbought" (Expensive). RSI < 30 is "Oversold" (Cheap).

    Your goal is to generate a comprehensive HTML report with FIVE separate sections.
    **CRITICAL**: Use the Google Search tool to fetch real-time data for team stats, recent news, and leaks.
    **SENTIMENT**: Based on the search results (news/stats), calculate a 'Sentiment Score' from 0 (Very Bearish) to 100 (Very Bullish).
    **CONTROVERSY**: Calculate a 'Controversy Rating' from 0 (Consensus) to 10 (High Conflict). High controversy means sources/analysts disagree on the outcome.
    Return ONLY valid HTML code. Do not include markdown code blocks.

    **STYLING INSTRUCTIONS**:
    Use the following color palette strictly:
    - Background: #000000
    - Primary Accent: #53277D
    - Secondary Accent: #00FFDD
    - Highlight: #FFB300
    - Text: #FCFCFC
    Style the HTML with a modern, dark-themed CSS using these colors.

    ### SECTION 1: Esports Markets
    For each unique category in the data (league-of-legends, valorant, cs2, dota-2), create a sub-section with a table:
    Resolves (endDate), Match, Category, Volume, Implied Odds, RSI Score, Sentiment Score, Controversy Rating, Team Stats, Analysis, Prediction.
    Format the "Resolves" column as a human-readable date+time (e.g. "Mar 09 18:00 UTC"). Use the endDate field from the data.
    If no active markets exist for a category, note it briefly and move on.
    
    ### SECTION 3: The Roundtable Discussion (Simulated)
    Simulate a debate among these 8 personas regarding the markets above:
    1. **"Safe Hands" Gimliwise Gamgee** (Conservative): Dislikes high 'volatility'. Only likes >75% odds.
    2. **"YOLO" Peregrin Took** (High Risk): Loves long shots (<30% odds) with high multipliers.
    3. **"Value" Aragorn** (Value Investor): Looks for mispriced odds (e.g., real chance 60%, market says 40%).
    4. **"Trend" Legolas** (Momentum): Loves high RSI (strong uptrend) but fears RSI > 80 (reversal risk).
    5. **"Skeptic" Gimli** (Contrarian): Bets against the crowd if the volume looks "dumb".
    6. **"Quant" Gandalf** (Data): Focuses on RSI and Volatility. Ignores narratives.
    7. **"Insider" Boromir** (News/Leaks): Obsessed with source credibility and leaks.
    8. **"Macro" Elrond** (Big Picture): Looks at external factors (economy, patch notes, regulation).
    
    **Task**:
    - Provide a "Meeting Minutes" summary where these personas argue about the best bets found in the data.
    - Highlight conflicts (e.g., Peregrin Took wants a risky bet, Gimliwise Gamgee opposes).
    - If there is a tie or lack of consensus, **The Chairman** (You) enters to make the final decision.
    
    ### SECTION 3.5: Deep Research & Counter-Arguments (Devil's Advocate)
    **CRITICAL STEP**: For the top 2 potential bets identified above, perform a specific Google Search to find reasons why they might FAIL.
    - Search for: "Why [Team A] will lose to [Team B]", "[Product] delay rumors", "Counter-thesis for [Market]".
    - List the strongest counter-argument found. If the counter-argument is too strong, DISCARD the bet.
    
    ### SECTION 4: Final Consensus Portfolio (${balance:.2f} Fund)
    Based on the Roundtable's agreement, allocate exactly ${balance:.2f}.
    **Strategy**: Diversified Fractional Kelly.
    1. **Spread Across Markets**: Target 5–10 bets across DIFFERENT matches and categories. Never put more than 30% of the fund into a single bet. More independent bets = lower variance = law of large numbers works in our favor.
    2. **Fractional Kelly**: Use 25–40% of the full Kelly-suggested size per bet. Full Kelly risks ruin on a bad day. Fractional Kelly preserves the bankroll long-term.
    3. **Persona Multiplier**: Each persona in the leaderboard has a budget multiplier (1.0x trusted, 0.75x caution, 0.5x struggling). Apply their multiplier to the Kelly allocation. Struggling personas still bet — just smaller. Do NOT skip their picks entirely; small diversified bets are better than zero exposure.
    4. **Consensus**: Only invest if at least 2 personas agreed (or Chairman overruled).
    5. **CRITICAL — MINIMUM BET**: Each market in the data has a "min_bets" field showing the EXACT minimum dollar amount per outcome (e.g. {{"Misa Esports": 3.88, "BIG": 2.12}}). You MUST allocate AT LEAST that amount for the chosen outcome, or skip the bet entirely. Never allocate less than the min_bets value for your chosen outcome.

    Output as a table:
    | Market | Resolves | Allocation | Primary Backer (Persona) | Rationale |
    (Include the endDate formatted as "Mar 09 18:00 UTC" in the Resolves column. Use the endDate field from the market data.)
    (Ensure sum is exactly ${balance:.2f})
    
    ### SECTION 6: JSON DATA (Machine Readable)
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
    
    ### SECTION 5: Projected Returns (The "Aftermath")
    Calculate the expected outcome of your portfolio based on the odds in the data.
    For each bet in the portfolio, include a row in a summary table:
    | Market | Outcome | Resolves | Investment | Potential Payout | Net Profit |
    (Resolves = endDate formatted as "Mar 09 18:00 UTC". Potential Payout = Investment / Price. Net Profit = Payout - Investment.)
    1. **Best Case Scenario**: If all your predictions are correct, what is the total value of the portfolio?
       (Formula per bet: Investment Amount / Current Price).
    2. **ROI Analysis**: Brief comment on the potential Return on Investment (e.g., "Expected to turn ${balance:.2f} into $X.XX").
    
    Data:
    {json.dumps(optimized_data, indent=2)}
    """

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