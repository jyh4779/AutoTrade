
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import yfinance as yf
import pandas as pd
import os

def collect_macro_data():
    print("Collecting Macro Economic Data (via yfinance)...")
    
    # Define Tickers
    # KRW=X: USD/KRW
    # ^IXIC: NASDAQ
    # ^SOX: PHLX Semiconductor (If blocked, try SMH ETF)
    tickers = {
        'USD_KRW': 'KRW=X',
        'NASDAQ': '^IXIC',
        'SOX': '^SOX',
        'SAMSUNG': '005930.KS'
    }
    
    data_frames = []
    
    for name, ticker in tickers.items():
        print(f" - Fetching {name} ({ticker})...")
        try:
            # Download full history
            df = yf.download(ticker, start='2015-01-01', progress=False)
            
            # Keep only Close (Adj Close is better for backtest)
            if 'Adj Close' in df.columns:
                df = df[['Adj Close']]
            elif 'Close' in df.columns:
                df = df[['Close']]
                
            # Flatten columns if MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
                
            df.rename(columns={df.columns[0]: name}, inplace=True)
            data_frames.append(df)
            
        except Exception as e:
            print(f"[ERROR] Failed to fetch {name}: {e}")

    # Merge All
    print("Merging data...")
    if not data_frames:
        print("[ERROR] No data collected.")
        return

    # Use Samsung index as base
    df_merged = data_frames[-1] # Samsung is last
    for i in range(len(data_frames)-1):
        df_merged = df_merged.join(data_frames[i], how='left')
    
    # Fill NA (Forward Fill for holidays)
    df_merged = df_merged.ffill()
    df_merged.dropna(inplace=True) 
    
    # Save
    output_dir = "D:\\ML\\data"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    output_path = os.path.join(output_dir, "samsung_macro_v4.csv")
    df_merged.to_csv(output_path)
    
    print(f"[SUCCESS] Macro data saved to {output_path}")
    print(df_merged.tail())

if __name__ == "__main__":
    collect_macro_data()