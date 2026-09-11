
import sys
import os
import sqlite3
from datetime import datetime
import pandas as pd

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.runners.stock_screener import MorningScreener
from src.markets.stocks.paper_trader import PaperTrader
from src.adapters.kis.kis_trader import KISTrader
from src.markets.stocks.strategy_manager import StrategyManager
import json
from src.core.observability.events import audit, now_kst, digest
from src.markets.stocks.strategy import allocate

def get_trader():
    if os.environ.get('ML_EXECUTION_MODE') == 'paper':
        return PaperTrader(db_path='D:/ML/data/paper_portfolio.db')
    config_path = "D:\\ML\\data\\config.json"
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        # If App Key exists, assume user wants REAL trading (or virtual KIS)
        if config.get("app_key") and len(config.get("app_key")) > 10:
            print("[INFO] Switching to KIS (Real/VTS) Trader.")
            return KISTrader()
    
    if os.environ.get('ML_EXECUTION_MODE') != 'paper':
        raise RuntimeError('Broker credentials missing; explicit paper mode required')
    return PaperTrader(db_path='D:/ML/data/paper_portfolio.db')

# --- Trading Constants ---
BUDGET_RATIO = 0.70

_DB_PATH = "D:\\ML\\data\\portfolio.db"

def get_dynamic_threshold(candidates, market_weak=False):
    # [B8] 임계값을 코드에 박지 않고 strategy_config.json 에서 읽는다.
    #      기존에는 base=0.70 하드코딩이라 설정 파일도 대시보드도 영향을 주지 못했다.
    base = StrategyManager().get_weights().get("score_threshold", 0.70)

    # 후보가 적다고 기준을 낮추던 완화 규칙은 제거한다.
    # "살 게 없으면 사지 않는다"가 회전율을 낮추는 가장 확실한 방법이고,
    # 후보 수는 종목의 품질과 무관하다.

    try:
        conn = sqlite3.connect(_DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT AVG(return_pct) FROM trade_log
            WHERE type='SELL' AND date >= datetime('now', '-5 days')
        """)
        recent_avg = c.fetchone()[0]
        conn.close()
        if recent_avg is not None and recent_avg < -1.0:
            base = min(base + 0.05, 0.75)
            print(f"[INFO] 최근 수익률 {recent_avg:.1f}% 부진 — threshold 상향: {base}")
    except Exception:
        pass

    if market_weak:
        base = min(base + 0.03, 0.75)
        print(f"[INFO] 시장 약세 감지 — threshold 상향: {base}")

    return base
MIN_CASH_THRESHOLD = 100000
MAX_STOCK_RATIO = 0.20

def run_auto_trade():
    events = audit()
    mode = events.mode
    from src.markets.stocks.calendar import require_trading_day
    events.emit('ROUTINE_STARTED', required=True, routine='morning')
    if not require_trading_day('morning'):
        events.emit('NO_TRADE_DECISION', reason='NON_TRADING_DAY')
        return
    if mode == 'live' and not ('09:15' <= now_kst().strftime('%H:%M') < '10:00'):
        events.emit('NO_TRADE_DECISION', reason='OUTSIDE_ENTRY_WINDOW')
        return
    bot = get_trader()
    if mode != 'shadow':
        bot.sell_all()
        if bot.get_holdings() or (hasattr(bot,'orders') and bot.orders.pending()):
            events.emit('NO_TRADE_DECISION', reason='PRIOR_POSITION_UNRESOLVED')
            return
    weights = StrategyManager().get_weights()
    events.emit('CONFIG_LOADED', required=True, component='auto_trade',effective_config=weights,
                effective_config_hash=digest(weights))
    balance = bot.get_balance()
    screener = MorningScreener(max_price=balance*MAX_STOCK_RATIO)
    candidates = screener.run() or []
    threshold = get_dynamic_threshold(candidates, market_weak=screener.market_weak)
    plan = allocate(candidates,balance,threshold,max_buys=weights['max_daily_buys'])
    events.emit('ALLOCATION_PROPOSED', required=True, scan_id=screener.scan_id,cash=balance,threshold=threshold,
                max_buys=weights['max_daily_buys'], candidates=candidates,
                allocations=[dict(symbol=c['code'],budget=b) for c,b in plan])
    planned={c['code'] for c,b in plan}
    for c in candidates:
        events.emit('SIGNAL_DECISION',required=True,scan_id=screener.scan_id,symbol=c['code'],score=c['score'],
                    threshold=threshold,selected=c['code'] in planned,
                    reason='SELECTED' if c['code'] in planned else ('SCORE_THRESHOLD' if c['score']<threshold else 'BUDGET_OR_DAILY_LIMIT'))
    if not screener.entry_allowed:
        events.emit('NO_TRADE_DECISION',required=True,reason='MARKET_GATE',scan_id=screener.scan_id,
                    evaluated_candidates=len(candidates),hypothetical_allocations=len(plan))
        events.emit('ROUTINE_FINISHED',routine='morning',orders_allowed=False)
        return
    if not plan:
        events.emit('NO_TRADE_DECISION',reason='NO_ELIGIBLE_ALLOCATION',scan_id=screener.scan_id)
        return
    remaining=balance
    for c,budget in plan:
        price=bot.get_current_price(c['code'])
        reason=None
        if not price or price<=0:
            reason='QUOTE_UNAVAILABLE'
        elif c.get('screener_price') and price/c['screener_price']>1.015:
            reason='PRICE_DRIFT'
        elif c.get('prev_close') and price/c['prev_close']>1.02:
            reason='GAP_LIMIT'
        if reason:
            events.emit('ENTRY_BLOCKED',symbol=c['code'],reason=reason)
            continue
        # No one-share fallback that can bypass the allocation or reserve.
        qty=int(min(budget,remaining-MIN_CASH_THRESHOLD)//price)
        if qty<=0:
            events.emit('ENTRY_BLOCKED',symbol=c['code'],reason='ALLOCATION_BELOW_ONE_SHARE')
            continue
        events.emit('ENTRY_EVALUATED',required=True,symbol=c['code'],price=price,qty=qty,budget=budget,
                    screen_price=c.get('screener_price'),prev_close=c.get('prev_close'),mode=mode)
        if mode=='shadow':
            events.emit('SHADOW_ORDER',symbol=c['code'],qty=qty,price=price)
            remaining-=qty*price
            continue
        filled=bot.buy(c['code'],c['name'],qty,score=c['score'])
        events.emit('ENTRY_RESULT',symbol=c['code'],fully_filled=bool(filled))
        if hasattr(bot,'orders') and bot.orders.pending():
            events.emit('ENTRY_BLOCKED',reason='UNRESOLVED_ORDER_STOPS_BATCH')
            break
        remaining=bot.get_balance()
    events.emit('ROUTINE_FINISHED',routine='morning')


if __name__ == '__main__':
    run_auto_trade()
