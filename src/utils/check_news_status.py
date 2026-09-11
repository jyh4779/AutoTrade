import pandas as pd
import os

def check_news_collection_status():
    path = "D:\\ML\\data\\stock_news_db.csv"
    
    if not os.path.exists(path):
        print("News DB file not found.")
        return

    try:
        df = pd.read_csv(path)
        print(f"Total News Collected: {len(df)}")
        print(f"Unique Stocks: {df['Code'].nunique()}")
        print(f"Date Range: {df['Date'].min()} ~ {df['Date'].max()}")
        
        # Check last processed stock
        last_stock = df['Code'].iloc[-1]
        print(f"Last Processed Stock Code: {last_stock}")
        
    except Exception as e:
        print(f"Error reading DB: {e}")

if __name__ == "__main__":
    check_news_collection_status()
