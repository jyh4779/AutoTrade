
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
import numpy as np
import ta
from sklearn.preprocessing import StandardScaler
import os

def preprocess_v4():
    print("Starting Preprocessing V4 (Log Returns & Macro)...")
    
    # 1. Load Data
    macro_path = "D:\\ML\\data\\samsung_macro_v4.csv"
    news_path = "D:\\ML\\data\\samsung_news_sentiment_5y_fast.csv"
    
    if not os.path.exists(macro_path):
        print("Macro data missing.")
        return

    df = pd.read_csv(macro_path, index_col='Date', parse_dates=True)
    
    # 2. Log Return Transformation (Core)
    # Price -> Return (Change Rate)
    cols_to_log = ['SAMSUNG', 'USD_KRW', 'NASDAQ', 'SOX']
    for col in cols_to_log:
        df[f'{col}_Ret'] = np.log(df[col] / df[col].shift(1))
        
    # 3. Add Tech Indicators (on Price, then normalize later)
    # RSI
    df['RSI'] = ta.momentum.rsi(df['SAMSUNG'], window=14)
    # MACD
    macd = ta.trend.MACD(df['SAMSUNG'])
    df['MACD'] = macd.macd_diff() # Histogram only
    
    # 4. Merge News
    if os.path.exists(news_path):
        news = pd.read_csv(news_path)
        news['Date'] = pd.to_datetime(news['Date'])
        # Group by date if multiple news, take mean
        news = news.groupby('Date')['Sentiment_Score'].mean().reset_index()
        news.set_index('Date', inplace=True)
        
        df = df.join(news, how='left')
        df['Sentiment_Score'] = df['Sentiment_Score'].fillna(0) # No news = Neutral
        
        # News Moving Average (Mood)
        df['News_MA3'] = df['Sentiment_Score'].rolling(3).mean().fillna(0)
        df['News_MA7'] = df['Sentiment_Score'].rolling(7).mean().fillna(0)
    else:
        df['Sentiment_Score'] = 0
        df['News_MA3'] = 0
        df['News_MA7'] = 0

    # 5. Create Target (High Bar)
    # Target: Next Day Return > 0.003 (0.3%)
    # Fees are usually 0.015~0.2% total. 0.3% is safe margin.
    next_ret = df['SAMSUNG_Ret'].shift(-1)
    df['Target'] = (next_ret > 0.003).astype(int)
    
    # 6. Drop NaNs
    df.dropna(inplace=True)
    
    # 7. Select Features
    features = [
        'SAMSUNG_Ret', 'USD_KRW_Ret', 'NASDAQ_Ret', 'SOX_Ret', # Macro Returns
        'RSI', 'MACD', # Tech
        'Sentiment_Score', 'News_MA3', 'News_MA7' # News
    ]
    
    # 8. Scaling (StandardScaler is better for Returns)
    scaler = StandardScaler()
    df[features] = scaler.fit_transform(df[features])
    
    # Save
    output_path = "D:\\ML\\data\\processed_samsung_v4.csv"
    df.to_csv(output_path)
    print(f"[SUCCESS] V4 Data Saved: {output_path}")
    print(f"Features: {features}")
    print(df[['SAMSUNG_Ret', 'Target']].tail())

if __name__ == "__main__":
    preprocess_v4()