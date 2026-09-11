
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
import numpy as np
import os

# 1. Load Data
stock_path = "D:\\ML\\data\\processed_samsung_v2.csv"
news_path = "D:\\ML\\data\\samsung_news_sentiment_5y_fast.csv"

if not os.path.exists(stock_path) or not os.path.exists(news_path):
    print("Files not found")
    exit(1)

df_stock = pd.read_csv(stock_path)
df_news = pd.read_csv(news_path)

# 2. Merge
# Prepare Date columns
df_stock['Date'] = pd.to_datetime(df_stock['Date'])
df_news['Date'] = pd.to_datetime(df_news['Date'])

# Merge left (keep all stock days)
df_merged = pd.merge(df_stock, df_news[['Date', 'Sentiment_Score']], on='Date', how='left')

# 3. Handle Missing News Days
# If no news, assume neutral (0.0) or ffill
df_merged['Sentiment_Score'].fillna(0.0, inplace=True)

# 4. Feature Engineering with News
# Add Moving Average of Sentiment (Market Mood)
import ta
# Sentiment MA (3-day, 7-day mood)
df_merged['Sent_MA3'] = df_merged['Sentiment_Score'].rolling(window=3).mean().fillna(0)
df_merged['Sent_MA7'] = df_merged['Sentiment_Score'].rolling(window=7).mean().fillna(0)

# Normalize Sentiment (already -1 to 1, but let's shift to 0~1 for consistency with others if needed, 
# but Tree models don't strictly care. Let's keep it raw or minmax.)
# Actually, let's leave it as is for XGBoost.

# Save V3 Data
output_path = "D:\\ML\\data\\processed_samsung_v3.csv"
df_merged.to_csv(output_path, index=False)
print(f"[SUCCESS] Merged data saved to: {output_path}")
print(df_merged[['Date', 'Close', 'Sentiment_Score', 'Sent_MA3']].tail())