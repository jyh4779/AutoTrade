from pykrx import stock
import pandas as pd
from datetime import datetime
import sys

def is_market_open_today():
    # 1. Check if Weekend
    now = datetime.now()
    if now.weekday() >= 5: # 5: Sat, 6: Sun
        return False, "주말(토/일)은 휴장입니다."

    # 2. Check KRX Business Day via pykrx
    today_str = now.strftime("%Y%m%d")
    
    try:
        # Get business days for the last 10 days
        # This will only return dates that the market was actually open
        # We use Samsung (005930) as a reference
        start_check = (now - pd.Timedelta(days=10)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start_check, today_str, "005930")
        
        if df.empty:
            return False, "데이터를 불러올 수 없습니다. (휴장 가능성 높음)"

        last_trading_day = df.index[-1].strftime("%Y%m%d")
        
        # If today is in the trading day index, market is open
        if last_trading_day == today_str:
            return True, "오늘은 정상 영업일입니다."
        else:
            return False, f"오늘은 휴장일(공휴일)입니다. (최근 영업일: {last_trading_day})"
            
    except Exception as e:
        return False, f"영업일 판단 중 오류 발생: {e}"

if __name__ == "__main__":
    is_open, msg = is_market_open_today()
    print(f"[Market Check] {msg}")
    if not is_open:
        sys.exit(1) # Exit with error code if closed
    else:
        sys.exit(0)
