
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
import time
from src.utils.llm_client import OllamaSentimentClient

_client = OllamaSentimentClient()

def analyze_sentiment(text, model="gemma3:4b", name="종목", code="unknown"):
    """
    헤드라인 텍스트의 감성 점수를 반환 (-1.0 ~ 1.0).
    실패 시 0.0 반환 (배치 스크립트 호환성 유지).
    """
    client = OllamaSentimentClient(model=model) if model != _client.model else _client
    result = client.score_headlines(name=name, code=code, headlines=[text])
    return result.score if result is not None else 0.0

if __name__ == "__main__":
    print("Starting sentiment analysis loop...")
    
    input_path = "D:\\ML\\data\\samsung_news_rss.csv"
    output_path = "D:\\ML\\data\\samsung_news_sentiment.csv"
    
    if not os.path.exists(input_path):
        print("Input file not found")
        exit(1)
        
    df = pd.read_csv(input_path)
    print(f"Loaded {len(df)} items. Processing top 20...")
    
    # Process top 20
    df_top = df.head(20).copy()
    scores = []
    
    for i, row in df_top.iterrows():
        title = row['Title']
        # Safe print for Windows console
        safe_title = title.encode('ascii', 'ignore').decode('ascii') 
        print(f"[{i+1}/{len(df_top)}] Analyzing...")
        
        score = analyze_sentiment(title)
        scores.append(score)
        print(f" -> Score: {score}")
        
    df_top['Sentiment_Score'] = scores
    
    # Save
    df_top.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"[SUCCESS] Saved to {output_path}")
    
    avg_score = df_top['Sentiment_Score'].mean()
    print(f"Average Sentiment Score: {avg_score:.4f}")