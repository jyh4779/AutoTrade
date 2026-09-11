
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import feedparser
import pandas as pd
import os
from datetime import datetime
import time
import calendar
import sys

# Force utf-8 for stdout
sys.stdout.reconfigure(encoding='utf-8')

def get_month_ranges(start_year, end_year):
    ranges = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            start_date = f"{year}-{month:02d}-01"
            _, last_day = calendar.monthrange(year, month)
            end_date = f"{year}-{month:02d}-{last_day}"
            if datetime.strptime(start_date, '%Y-%m-%d') > datetime.now():
                break
            ranges.append((start_date, end_date))
    return ranges

def fetch_google_news(query, start_date, end_date):
    full_query = f"{query} after:{start_date} before:{end_date}"
    encoded_query = full_query.replace(' ', '+').replace(':', '%3A')
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        for entry in feed.entries:
            try:
                pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %Z')
            except:
                pub_date = entry.published
            
            news_items.append({
                'Date': pub_date,
                'Title': entry.title,
                'Link': entry.link
            })
        return news_items
    except Exception as e:
        print(f"[ERROR] Fetch failed for {start_date}: {e}")
        return []

if __name__ == "__main__":
    query = "SK하이닉스"
    output_path = "D:\\ML\\data\\skhynix_news_5y.csv"
    
    print(f"Starting News Collection for {query}...")
    
    ranges = get_month_ranges(2021, 2026)
    total_collected = 0
    buffer = []
    
    # Check if exists to append
    file_exists = os.path.exists(output_path)
    if file_exists:
        print("Appending to existing file...")
    
    for i, (start, end) in enumerate(ranges):
        items = fetch_google_news(query, start, end)
        buffer.extend(items)
        total_collected += len(items)
        
        # Save every 100 items (or close to it, essentially every chunk/month)
        if len(buffer) >= 100:
            df = pd.DataFrame(buffer)
            # Pre-processing dates to string for CSV consistency
            df['Date'] = df['Date'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if isinstance(x, datetime) else str(x))
            
            mode = 'a' if os.path.exists(output_path) else 'w'
            header = not os.path.exists(output_path)
            
            df.to_csv(output_path, index=False, encoding='utf-8-sig', mode=mode, header=header)
            print(f"[SAVE] Saved {len(buffer)} items. (Total: {total_collected})")
            buffer = [] # Clear buffer
            
        # Report trigger for Agent (every 1000 lines approx)
        if total_collected % 1000 < 100 and total_collected > 0: # Rough check
             print(f"[REPORT] Progress: {total_collected} items collected.")
             
        time.sleep(1.0) # Be polite
        
    # Save remaining
    if buffer:
        df = pd.DataFrame(buffer)
        df['Date'] = df['Date'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if isinstance(x, datetime) else str(x))
        mode = 'a' if os.path.exists(output_path) else 'w'
        header = not os.path.exists(output_path)
        df.to_csv(output_path, index=False, encoding='utf-8-sig', mode=mode, header=header)
        print(f"[SAVE] Final save {len(buffer)} items.")

    print(f"[COMPLETE] Total collected: {total_collected}")