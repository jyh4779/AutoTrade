"""Pure decision rules shared by live trading and replay. No IO or wall clock."""
import math


def expected_volume_fraction(elapsed_minutes):
    m = max(1., elapsed_minutes)
    if m <= 30:
        return max(.01, m * .2 / 30)
    if m <= 330:
        return .2 + (m - 30) * .5 / 300
    if m < 390:
        return .7 + (m - 330) * .3 / 60
    return 1.


def volume_score(cumulative_volume, average_volume, elapsed_minutes):
    if not all(math.isfinite(x) for x in (cumulative_volume, average_volume, elapsed_minutes)):
        raise ValueError('non_finite_volume')
    if cumulative_volume < 0 or average_volume <= 0:
        raise ValueError('invalid_volume')
    return min(cumulative_volume / expected_volume_fraction(elapsed_minutes) / average_volume / 2, 1.)


def technical_scores(history, price, cumulative_volume, elapsed_minutes, weights, pre_mode=False):
    if len(history) < 10:
        return dict(vol=0.,sd=0.,ts=0.,reason='INSUFFICIENT_HISTORY')
    last=history[-1]
    required=[last[k] for k in ('Close','Volume','Vol_MA5','RSI','MA20')]
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in required):
        raise ValueError('invalid_history')
    if last['Close']<=0 or history[-2]['Close']<=0 or history[-9]['Close']<=0:
        raise ValueError('invalid_history_price')
    ref=price if price is not None else last['Close']
    if ref<=0 or not math.isfinite(ref):
        raise ValueError('invalid_current_price')
    gap=ref/last['Close']-1
    reason=None
    if last['Close']/history[-2]['Close']-1>=.10:
        reason='PRIOR_SURGE'
    elif last['RSI']>=75:
        reason='RSI_OVERBOUGHT'
    elif gap>=.05:
        reason='GAP_UP'
    elif gap<=-.03:
        reason='GAP_DOWN'
    if reason:
        return dict(vol=0.,sd=0.,ts=0.,reason=reason)
    high=max(h['High'] for h in history[-5:]);low=min(h['Low'] for h in history[-5:])
    if low<=0 or not all(math.isfinite(x) for x in (high,low)):
        raise ValueError('invalid_range')
    vol=1-min(max((high-low)/low,0),.3)/.3
    if pre_mode:
        sd=min(last['Volume']/last['Vol_MA5']/2,1.) if last['Vol_MA5']>0 else 0.
    else:
        if cumulative_volume is None:
            raise ValueError('current_volume_missing')
        sd=volume_score(cumulative_volume,last['Vol_MA5'],elapsed_minutes)
    peak=weights.get('momentum_peak',.02);width=weights.get('momentum_width',.035)
    if width<=0:
        raise ValueError('invalid_momentum_width')
    momentum=ref/history[-9]['Close']-1
    ts=math.exp(-((momentum-peak)/width)**2)
    if last['Close']<=last['MA20']:ts*=.3
    if gap>=.03:ts*=.3
    elif gap>=.015:ts*=.6
    elif gap<=-.01:ts*=.5
    return dict(vol=vol,sd=sd,ts=ts,reason='SCORED')


def exit_reason(price, average, target=.05, stop=-.03, time_exit=False):
    if time_exit:
        return 'TIME'
    if price <= 0 or average <= 0 or not all(math.isfinite(x) for x in (price,average)):
        return 'INVALID_PRICE'
    ret = price / average - 1
    if ret >= target - 1e-12:
        return 'TAKE_PROFIT'
    if ret <= stop + 1e-12:
        return 'STOP_LOSS'
    return 'HOLD'



def combined_score(tech, sentiment, fundamental, weights):
    values = [tech, sentiment, fundamental]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError('invalid_factor')
    if not (0 <= tech <= 1 and -1 <= sentiment <= 1 and 0 <= fundamental <= 1):
        raise ValueError('factor_out_of_range')
    w = [weights[k] for k in ('tech_weight', 'ai_weight', 'fa_weight')]
    if not all(math.isfinite(v) and v >= 0 for v in w) or not math.isclose(sum(w), 1., abs_tol=.002):
        raise ValueError('invalid_weights')
    return sum(a*b for a,b in zip(values,w))




from src.core.risk.allocation import allocate
