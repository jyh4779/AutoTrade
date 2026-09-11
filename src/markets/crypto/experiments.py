"""Versioned challenger, preserving the original strategy score."""
import math
from src.markets.crypto.strategy import closed_bars, number

EXPERIMENT = dict(id='relative_entry_v1',threshold=.70,
                  weights=dict(trend=.25,relative=.20,volume=.20,entry=.20,liquidity=.15))


def challenger(raw, at, baseline, btc_return):
    if btc_return is None:raise ValueError('BENCHMARK_UNAVAILABLE')
    bars=closed_bars(raw,at)
    prices=[number(b['trade_price']) for b in bars]
    returns=[b/a-1 for a,b in zip(prices,prices[1:])]
    mean=sum(returns)/len(returns)
    volatility=max(.001,math.sqrt(sum((r-mean)**2 for r in returns)/len(returns)))
    clamp=lambda v:max(0.,min(1.,v))
    relative=baseline['hour_return']-btc_return
    distance=prices[-1]/(sum(prices[-20:])/20)-1
    factors=dict(trend=baseline['trend'],relative=clamp(.5+relative/(4*volatility)),
        volume=baseline['relative_volume'],entry=clamp(1-abs(distance)/(4*volatility)),
        liquidity=clamp(1-baseline['spread']/.002))
    contributions={k:factors[k]*w for k,w in EXPERIMENT['weights'].items()}
    return dict(strategy=EXPERIMENT['id'],score=sum(contributions.values()),
                threshold=EXPERIMENT['threshold'],factors=factors,contributions=contributions,
                raw=dict(volatility=volatility,relative_return=relative,distance=distance))
