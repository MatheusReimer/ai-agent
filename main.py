import os
import sys
import shutil
from datetime import datetime
from polymarket_api import get_markets
from ai_analyst import analyze_with_gemini
from trader import execute_portfolio, validate_portfolio
from check_balance import check_usdc_balance
from results_tracker import get_performance_summary, record_bets
from redeemer import redeem_winnings
from emailer import send_report
from eth_account import Account
from config import PRIVATE_KEY, PURCHASE_PASSKEY, POLYMARKET_PROXY_ADDRESS

AUTO_MODE = "--auto" in sys.argv

if __name__ == "__main__":
    # 0. Check Funds
    balance = check_usdc_balance()

    # If balance is 0, try to help the user fund it via Coinbase
    if balance is not None and balance < 0.5:
        print("\n--- ⚠️ INSUFFICIENT FUNDS ---")
        
        # Wait for user to fund the wallet
        while balance < 0.5:
            print("\n--- WAITING FOR FUNDS ---")
            if POLYMARKET_PROXY_ADDRESS:
                print(f"👉 Ensure funds are in Proxy Address: {POLYMARKET_PROXY_ADDRESS}")
            elif PRIVATE_KEY:
                try:
                    print(f"👉 Transfer funds to Signer Address: {Account.from_key(PRIVATE_KEY).address}")
                except: pass

            try:
                choice = input("Action Required: Press ENTER to re-check (or type 'skip' / 'force'): ")
            except KeyboardInterrupt:
                print("\nExiting...")
                exit()
            if choice.lower() == "skip":
                print("Proceeding in SIMULATION MODE (No real trades).")
                break
            if choice.lower() == "force":
                print("⚠️ FORCING REAL TRADING (Ignoring Balance Check)...")
                break
            balance = check_usdc_balance()
            if balance >= 0.5:
                print(f"✅ Funds Received! New Balance: ${balance:.2f}")

    redeem_winnings()

    markets = get_markets()
    if not markets:
        print("\n--- NO MARKETS FOUND ---")
        print(f"No upcoming matches within the next {__import__('polymarket_api').MAX_DAYS_TO_RESOLVE} day(s) that haven't started yet.")
        print("Try increasing MAX_DAYS_TO_RESOLVE in polymarket_api.py or run again later.")
        exit(0)

    if markets:
        print(f"\n--- DATA FETCH COMPLETE: {len(markets)} MARKETS FOUND ---")
        # 1. Load historical performance and pass to analyst
        history_summary = get_performance_summary()
        print(f"\n--- PERFORMANCE HISTORY ---\n{history_summary}\n")
        # Pass effective budget: divide by 1.05 to pre-account for the 5% fill_price premium
        effective_balance = round(balance / 1.05, 2)
        portfolio, html_content = analyze_with_gemini(markets, history_summary=history_summary, balance=effective_balance)
        
        # 2. Validate portfolio before asking user
        portfolio = validate_portfolio(portfolio, markets)

        # 3. Rescale portfolio to use full balance (validation bumps may shift totals)
        if portfolio:
            total_allocated = sum(float(b["amount"]) for b in portfolio)
            if total_allocated > 0 and abs(total_allocated - effective_balance) > 0.01:
                scale = effective_balance / total_allocated
                for b in portfolio:
                    b["amount"] = round(float(b["amount"]) * scale, 2)
                diff = round(effective_balance - sum(float(b["amount"]) for b in portfolio), 2)
                if diff != 0:
                    portfolio[-1]["amount"] = round(float(portfolio[-1]["amount"]) + diff, 2)
                print(f"  Portfolio rescaled: ${total_allocated:.2f} → ${effective_balance:.2f}")

        if portfolio:
            print(f"\nAI generated {len(portfolio)} executable bets.")

            if AUTO_MODE:
                confirmed = bool(PURCHASE_PASSKEY)
                if not confirmed:
                    print("❌ Auto mode: PURCHASE_PASSKEY missing, skipping trades.")
            else:
                confirm = input("Do you want to execute these trades with REAL MONEY? (yes/no): ")
                confirmed = confirm.lower() == "yes"
                if confirmed and not PURCHASE_PASSKEY:
                    print("❌ Error: PURCHASE_PASSKEY is missing in .env.")
                    confirmed = False
                elif confirmed:
                    password = input("🔒 Enter PURCHASE_PASSKEY to confirm: ")
                    confirmed = password == PURCHASE_PASSKEY
                    if not confirmed:
                        print("❌ Incorrect password. Trading aborted.")

            if confirmed:
                print("✅ Executing trades...")
                placed = execute_portfolio(portfolio, markets, balance=balance)
                if placed:
                    record_bets(placed, markets)
                # Archive report
                reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
                os.makedirs(reports_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                archived = os.path.join(reports_dir, f"report_{ts}.html")
                shutil.copy2("esports_analysis.html", archived)
                print(f"📁 Report archived to {archived}")
                # Send email
                send_report(html_content, history_summary, placed or [])
            elif not AUTO_MODE:
                print("Trading skipped.")