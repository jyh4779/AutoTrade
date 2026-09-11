
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
import os

path = "D:\\ML\\data\\skhynix_news_sentiment.csv"
if os.path.exists(path):
    try:
        df = pd.read_csv(path)
        print(f"Current Progress: {len(df)} items processed.")
        if not df.empty:
            print(f"Last Processed Date: {df.iloc[-1]['Date']}")
    except Exception as e:
        print(f"Error reading file: {e}")
else:
    print("File not found. Starting from scratch.")