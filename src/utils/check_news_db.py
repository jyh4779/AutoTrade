
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
import os

path = "D:\\ML\\data\\stock_news_db.csv"

if os.path.exists(path):
    try:
        df = pd.read_csv(path)
        print(f"Total Rows: {len(df)}")
        print(f"Unique Stocks: {df['Code'].nunique()}")
        print(f"Date Range: {df['Date'].min()} ~ {df['Date'].max()}")
        print("-" * 30)
        print("Collected Stocks (Sample):")
        print(df['Code'].unique()[:10])
    except Exception as e:
        print(f"Error reading DB: {e}")
else:
    print("No DB file found.")