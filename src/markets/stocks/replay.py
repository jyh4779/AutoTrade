import argparse
import json
import math
import sqlite3
from pathlib import Path
from src.core.observability.events import ROOT
from src.markets.stocks.strategy import technical_scores, combined_score, exit_reason


def simulate_trade(bars, entry_time='091700', exit_time='151000', target=.05, stop=-.03, sell_cost=.00198):
    by={b['stck_cntg_hour']:b for b in bars}
    if entry_time not in by or exit_time not in by:
        return dict(status='UNKNOWN',reason='required_bar_missing')
    entry=float(by[entry_time]['stck_oprc'])
    if entry<=0:
        return dict(status='UNKNOWN',reason='invalid_entry')
    price=float(by[exit_time]['stck_oprc']);reason='TIME';ts=exit_time
    for t,b in sorted(by.items()):
        if not entry_time<=t<exit_time:continue
        op,hi,lo=[float(b[k]) for k in ('stck_oprc','stck_hgpr','stck_lwpr')]
        at_open=exit_reason(op,entry,target,stop)
        if at_open in ('STOP_LOSS','TAKE_PROFIT'):
            price,reason,ts=op,at_open,t;break
        take=hi>=entry*(1+target);loss=lo<=entry*(1+stop)
        if take and loss:
            return dict(status='UNKNOWN',reason='intrabar_order_ambiguous')
        if take or loss:
            price=entry*(1+target if take else 1+stop)
            reason='TAKE_PROFIT' if take else 'STOP_LOSS';ts=t;break
    return dict(status='PASS',reason=reason,entry=entry,exit=price,exit_time=ts,
                net_return=price*(1-sell_cost)/entry-1,fill_model='ideal_barrier_no_slippage',
                limitations=['30_second_polling_not_reproduced','tick_rounding_not_reproduced'])


def summarize(returns):
    values=[float(r) for r in returns if r is not None and math.isfinite(r)]
    if not values:
        return dict(count=0,mean=None,win_rate=None,profit_factor=None)
    gains=sum(max(r,0) for r in values);losses=-sum(min(r,0) for r in values)
    return dict(count=len(values),mean=sum(values)/len(values),win_rate=sum(r>0 for r in values)/len(values),
                profit_factor=gains/losses if losses else None)


def replay_day(root, day, override_weights=None):
    root=Path(root);path=root/'data/audit.db'
    if not path.exists():
        return [dict(status='UNKNOWN',reason='audit_database_missing')]
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:
        rows=[json.loads(r[0]) for r in c.execute('SELECT payload FROM events WHERE day=? ORDER BY seq',(day,))]
        snapshots={r[0]:json.loads(r[1]) for r in c.execute('SELECT id,payload FROM snapshots')}
    configs={e['session_id']:e['effective_config'] for e in rows if e['event_type']=='CONFIG_LOADED' and e['component']=='screener'}
    data={(e['scan_id'],e['symbol']):e for e in rows if e['event_type']=='DATA_SNAPSHOT'}
    scores={(e['scan_id'],e['symbol']):e for e in rows if e['event_type']=='SCORE_COMPUTED'}
    result=[]
    for e in rows:
        if e['event_type']!='TECH_COMPUTED' or e['pre_mode']:continue
        key=(e['scan_id'],e['symbol']);d=data.get(key);w=configs.get(e['session_id'])
        if not d or not w or d['snapshot_id'] not in snapshots:
            result.append(dict(symbol=e['symbol'],status='UNKNOWN',reason='snapshot_or_config_missing'));continue
        snap=snapshots[d['snapshot_id']]
        if d['history_date']>=day:
            result.append(dict(symbol=e['symbol'],status='FAIL',reason='future_history'));continue
        try:
            effective=override_weights or w
            t=technical_scores(snap['history'],snap['quote']['price'],e['volume'],e['elapsed_minutes'],effective)
            tech=.3*t['vol']+.3*t['sd']+.4*t['ts']
            item=dict(symbol=e['symbol'],scan_id=e['scan_id'],tech=tech,
                      status='EXPERIMENT' if override_weights else ('PASS' if math.isclose(tech,e['tech'],abs_tol=1e-9) else 'FAIL'))
            s=scores.get(key)
            if s:
                value=combined_score(tech,s['sentiment'],s['fundamental'],effective)
                item.update(score=value,passes_base_threshold=value>=effective['score_threshold'])
                if not override_weights and not math.isclose(value,s['score'],abs_tol=1e-9):item['status']='FAIL'
            else:
                item['score_status']='UNKNOWN_NO_HISTORICAL_NEWS_OR_FINANCIAL_SCORE'
            result.append(item)
        except (ValueError,TypeError,KeyError):
            result.append(dict(symbol=e['symbol'],status='UNKNOWN',reason='invalid_snapshot'))
    return result or [dict(status='UNKNOWN',reason='no_replayable_decisions')]


def main():
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--weights',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();w=json.loads(a.weights.read_text(encoding='utf-8')) if a.weights else None
    report=dict(day=a.date,kind='experiment' if w else 'decision_replay',results=replay_day(a.root,a.date,w),
                performance_validation='NOT_ESTABLISHED',warning='Not a complete portfolio or execution backtest')
    out=a.output or a.root/'docs/audit'/(a.date+'_replay.json');out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(out)


if __name__=='__main__':main()
