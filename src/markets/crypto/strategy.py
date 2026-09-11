"""Experimental 15-minute momentum ranking. Not validated for live trading."""
from datetime import datetime, timezone, timedelta
import math

POLICY = dict(strategy='upbit_krw_momentum_v1', max_symbols=20,
              minimum_turnover_24h=1_000_000_000, max_spread=.002,
              minimum_top5_depth_krw=5_000_000, score_threshold=.65,
              btc_hour_loss_limit=-.03)


def number(value):
    n=float(value)
    if not math.isfinite(n):raise ValueError('NON_FINITE')
    return n


def select_universe(markets, tickers, policy, previous=()):
    quotes={q['market']:q for q in tickers}
    eligible=[];decisions=[]
    for market in markets:
        symbol=market['market']
        if not symbol.startswith('KRW-'):continue
        reason=None
        event=market.get('market_event')
        if not isinstance(event,dict) or 'warning' not in event or 'caution' not in event:
            reason='MARKET_STATUS_UNKNOWN'
        elif event['warning'] or any(event['caution'].values()):
            reason='MARKET_WARNING'
        quote=quotes.get(symbol)
        try:
            turnover=number(quote['acc_trade_price_24h']) if quote else 0
            if not quote:reason=reason or 'TICKER_MISSING'
            elif turnover<policy['minimum_turnover_24h']:reason=reason or 'TURNOVER_FLOOR'
        except (ValueError,KeyError,TypeError):
            turnover=0;reason=reason or 'TICKER_INVALID'
        item=dict(symbol=symbol,name=market.get('korean_name',symbol),turnover=turnover,reason=reason)
        decisions.append(item)
        if reason is None:eligible.append(item)
    eligible.sort(key=lambda x:(-x['turnover'],x['symbol']))
    retained=[x for i,x in enumerate(eligible) if x['symbol'] in previous and i<policy['max_symbols']+5]
    selected=(retained+[x for x in eligible if x not in retained])[:policy['max_symbols']]
    keep={x['symbol'] for x in selected}
    for d in decisions:
        if d['reason'] is None:d['reason']='SELECTED' if d['symbol'] in keep else 'RANK_LIMIT'
    return selected,decisions


def closed_bars(raw, at):
    rows={}
    for bar in raw:
        ts=datetime.fromisoformat(bar['candle_date_time_utc']).replace(tzinfo=timezone.utc)
        if ts+timedelta(minutes=15)<=at:
            if ts in rows and rows[ts]!=bar:raise ValueError('CONFLICTING_CANDLE')
            rows[ts]=bar
    ordered=sorted(rows)
    if len(ordered)<25:raise ValueError('INSUFFICIENT_CLOSED_BARS')
    ordered=ordered[-25:]
    if any(b-a!=timedelta(minutes=15) for a,b in zip(ordered,ordered[1:])):
        raise ValueError('MISSING_CANDLE_INTERVAL')
    if not timedelta(0)<=(at-ordered[-1]-timedelta(minutes=15))<timedelta(minutes=15):
        raise ValueError('STALE_CANDLES')
    return [rows[t] for t in ordered]


def evaluate(raw, books, symbol, at, policy):
    if any(b.get('market')!=symbol for b in raw):raise ValueError('CANDLE_MARKET_MISMATCH')
    bars=closed_bars(raw,at)
    close=[number(b['trade_price']) for b in bars]
    volume=[number(b['candle_acc_trade_volume']) for b in bars]
    if min(close)<=0 or min(volume)<0:raise ValueError('INVALID_CANDLE_VALUE')
    if len(books)!=1 or books[0].get('market')!=symbol:raise ValueError('ORDERBOOK_MISMATCH')
    book=books[0]
    age=at.timestamp()-number(book['timestamp'])/1000
    if not -5<=age<=30:raise ValueError('STALE_ORDERBOOK')
    units=book['orderbook_units'][:5]
    if not units:raise ValueError('EMPTY_ORDERBOOK')
    ask=number(units[0]['ask_price']);bid=number(units[0]['bid_price'])
    if bid<=0 or ask<bid:raise ValueError('INVALID_SPREAD')
    spread=(ask-bid)/((ask+bid)/2)
    depth=min(sum(number(u[p])*number(u[q]) for u in units)
              for p,q in [('ask_price','ask_size'),('bid_price','bid_size')])
    hour_return=close[-1]/close[-5]-1
    mean=sum(close[-20:])/20
    trend=max(0,min(1,.5+(close[-1]/mean-1)/.04))
    momentum=max(0,min(1,.5+hour_return/.04))
    average=sum(volume[-21:-1])/20
    if average<=0:raise ValueError('INVALID_AVERAGE_VOLUME')
    relative_volume=min(1,volume[-1]/average/2)
    score=.4*trend+.4*momentum+.2*relative_volume
    reason='SPREAD_LIMIT' if spread>policy['max_spread'] else (
        'DEPTH_FLOOR' if depth<policy['minimum_top5_depth_krw'] else (
        'SCORE_THRESHOLD' if score<policy['score_threshold'] else 'CANDIDATE'))
    return dict(symbol=symbol,score=score,trend=trend,momentum=momentum,
        relative_volume=relative_volume,hour_return=hour_return,spread=spread,depth_krw=depth,
        price=close[-1],reason=reason,eligible=reason=='CANDIDATE')
