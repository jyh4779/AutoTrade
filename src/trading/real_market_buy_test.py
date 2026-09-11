
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.morning_screener import MorningScreener
from src.trading.kis_trader import KISTrader
from src.trading.kis_api import KISApi
from datetime import datetime
import pandas as pd
import sqlite3

def real_market_buy_test():
    print(f"\n[LIVE TEST] Executing Real Trade Command: {datetime.now()}")
    
    # 1. Initialize KIS Trader
    trader = KISTrader()
    
    # 2. Run Screener to find the best stock RIGHT NOW
    print("[STEP 1] Scanning market for top pick...")
    screener = MorningScreener()
    screener.load_data()
    screener.scan_tech()
    
    if not screener.candidates:
        print("[FAIL] No technical candidates found today.")
        return

    # Analyze News for candidates to find the absolute winner
    scored_candidates = []
    # Limit to top 5 by volume for speed
    sorted_tech = sorted(screener.candidates, key=lambda c: screener.stocks[c].iloc[-1]['Volume'], reverse=True)[:5]
    
    print(f"[STEP 2] Analyzing news for top {len(sorted_tech)} candidates...")
    for code in sorted_tech:
        score = screener.analyze_news(code)
        name = screener.names.get(code, code)
        print(f" - {name} ({code}): AI Score {score:.2f}")
        scored_candidates.append({'code': code, 'name': name, 'score': score})
        
    # Pick the one with highest score
    scored_candidates.sort(key=lambda x: x['score'], reverse=True)
    winner = scored_candidates[0]
    
    if winner['score'] < 0.1:
        print("[INFO] No strongly positive news found. Picking the best available.")
        
    print(f"\n🏆 Winner Selected: {winner['name']} ({winner['code']}) with Score {winner['score']:.2f}")

    # 3. Check Real Balance
    balance = trader.get_balance()
    print(f"[BALANCE] Real Cash Available: {balance:,.0f} KRW")
    
    if balance < 10000:
        print("[FAIL] Insufficient real balance to trade.")
        return

    # 4. Strategy: Invest 20% of balance for this test
    target_amount = balance * 0.2
    price = trader.get_current_price(winner['code'])
    
    if not price:
        print("[FAIL] Could not get real-time price.")
        return
        
    qty = int(target_amount // price)
    
    # Rule: If qty is 0 but we have enough for 1 share, buy 1
    if qty == 0 and balance >= price:
        print(f" - Budget ({target_amount:,.0f}) < Price ({price:,.0f}). Buying 1 share as requested.")
        qty = 1
        
    if qty > 0:
        print(f"[EXECUTE] Placing REAL BUY ORDER: {winner['name']} x {qty} at approx {price:,.0f}")
        success = trader.buy(winner['code'], winner['name'], qty)
        if success:
            print("[SUCCESS] Live trade test complete.")
        else:
            print("[FAIL] Real order execution failed.")
    else:
        print("[FAIL] Calculated quantity is 0. Check balance vs stock price.")

if __name__ == "__main__":
    real_market_buy_test()
