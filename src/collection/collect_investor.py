
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from pykrx import stock
import pandas as pd
import time
import os

def collect_investor_data(code='005930', start_date='20150101', end_date='20260210'):
    print(f"Collecting Investor Data for {code} ({start_date} ~ {end_date})...")
    
    try:
        # 투자자별 거래실적 추이 (순매수)
        df = stock.get_market_trading_value_by_date(start_date, end_date, code, on='순매수')
        
        # Columns might be garbled in Windows console, but are consistent in order.
        # Expected: ['기관합계', '기타법인', '개인', '외국인합계', '전체'] (KRX default)
        # Check column count just in case
        print(f"Columns count: {len(df.columns)}")
        
        # Mapping by Index (Safer)
        # 0: Inst, 1: Etc, 2: Individual, 3: Foreigner, 4: Total
        # NOTE: Verify order by printing first row values if unsure, but standard is Inst/Indiv/Foreign
        
        # Let's assume standard order:
        # Rename all
        df.columns = ['Institution', 'Corp_Etc', 'Individual', 'Foreigner', 'Total']
        
        # Select important ones
        cols_to_keep = ['Institution', 'Individual', 'Foreigner']
        df = df[cols_to_keep]
        
        # Save
        output_dir = "D:\\ML\\data"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        output_path = os.path.join(output_dir, "samsung_investor.csv")
        df.to_csv(output_path)
        
        print(f"[SUCCESS] Investor data saved to {output_path}")
        print(df.tail())
        
    except Exception as e:
        print(f"[ERROR] Failed to fetch investor data: {e}")

if __name__ == "__main__":
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    collect_investor_data(end_date=today)