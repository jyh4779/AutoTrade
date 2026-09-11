
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from pykrx import stock
import pandas as pd
import os
import time
from datetime import datetime, timedelta

def collect_market_data():
    print("Fetching KOSPI 200 & KOSDAQ 150 tickers...")
    
    today = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d") # 1 Year
    
    # Get Tickers
    kospi200 = stock.get_index_portfolio_deposit_file("1028") # KOSPI 200
    kosdaq150 = stock.get_index_portfolio_deposit_file("2203") # KOSDAQ 150
    
    targets = kospi200 + kosdaq150
    print(f"Total Targets: {len(targets)}")
    
    output_dir = "D:\\ML\\data\\stocks"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    print(f"Collecting OHLCV ({start_date} ~ {today})...")
    
    for i, code in enumerate(targets):
        try:
            # Fetch Price
            df = stock.get_market_ohlcv_by_date(start_date, today, code)
            
            # Save
            if not df.empty:
                df.to_csv(f"{output_dir}\\{code}.csv")
            
            if i % 50 == 0:
                print(f"[{i}/{len(targets)}] Processed...")
                
            time.sleep(0.1) # Prevent blocking
            
        except Exception as e:
            print(f"[ERROR] {code}: {e}")
            
    print("[SUCCESS] All stock data collected.")

if __name__ == "__main__":
    collect_market_data()