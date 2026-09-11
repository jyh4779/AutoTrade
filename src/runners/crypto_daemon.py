from src.markets.crypto.runtime import storage_path
"""Continuous public-only paper trading: evaluation and monitoring are independent."""
import argparse
import json
import os
import time
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from src.core.observability.events import ROOT
from src.core.observability.processes import Singleton
from src.adapters.upbit.public import PublicAPI
from src.markets.crypto.research import Research
from src.markets.crypto.strategy import POLICY,closed_bars,number
from src.runners.crypto import run
from src.reporting.crypto_feedback import report as feedback_report


def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.'+uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    tmp.replace(path)


def monitor(root,api=None,aggregate=True):
    api=api or PublicAPI()
    storage=storage_path(root)
    ledger=Research(storage/'data/research.db')
    now=datetime.now(timezone.utc)
    symbols=ledger.watch_symbols(now.timestamp())
    errors=[];actions=[];allowed=False;eligible=set()
    try:
        markets=api.markets()
        eligible={m['market'] for m in markets if m['market'].startswith('KRW-')
                  and isinstance(m.get('market_event'),dict)
                  and m['market_event'].get('warning') is False
                  and isinstance(m['market_event'].get('caution'),dict)
                  and not any(m['market_event']['caution'].values())}
        bars=closed_bars(api.candles('KRW-BTC',now),now)
        allowed=number(bars[-1]['trade_price'])/number(bars[-5]['trade_price'])-1>=POLICY['btc_hour_loss_limit']
    except Exception as exc:
        errors.append(dict(stage='entry_gate',error=type(exc).__name__))
    for symbol in sorted(symbols):
        try:
            books=api.orderbook(symbol)
            if len(books)!=1:raise ValueError('ORDERBOOK_UNAVAILABLE')
            observed=datetime.now(timezone.utc).timestamp()
            actions.extend(ledger.advance(symbol,books[0],observed,allowed and symbol in eligible))
        except Exception as exc:
            errors.append(dict(symbol=symbol,error=type(exc).__name__))
    result=dict(at=datetime.now(timezone.utc).isoformat(),pid=os.getpid(),mode='shadow',
        watched=len(symbols),actions=actions,errors=errors,status='WARN' if errors else 'PASS',
        orders_submitted=0,observation_interval_target_seconds=15,
        continuous_price_path_verified=False)
    if aggregate:
        result['feedback']=ledger.feedback()
        save(storage/'reports/performance_latest.json',dict(at=result['at'],feedback=result['feedback']))
        save(storage/'reports/feedback.json',feedback_report(ledger.path))
    save(storage/'reports/paper_latest.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description='Upbit KRW continuous paper trading; public API only')
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--once',action='store_true',help='one monitor pass; no signal evaluation')
    args=parser.parse_args()
    guard=Singleton(storage_path(args.root),'crypto:upbit:shadow')
    if not guard.acquire():return 75
    status=storage_path(args.root)/'reports/daemon.json'
    pool=ThreadPoolExecutor(max_workers=1)
    future=None;last_bucket=None;last_aggregate=0
    stopping=threading.Event()
    previous={sig:signal.signal(sig,lambda *_:stopping.set()) for sig in (signal.SIGTERM,signal.SIGINT)}
    try:
        while not stopping.is_set():
            start=time.monotonic()
            bucket=int(time.time()//900)
            if future is not None and future.done():
                try:
                    out,result=future.result()
                    save(status.with_name('evaluation_latest.json'),dict(path=str(out),status=result['status']))
                except Exception as exc:
                    save(status.with_name('evaluation_latest.json'),dict(status='FAIL',error=type(exc).__name__))
                future=None
            if not args.once and bucket!=last_bucket and future is None:
                future=pool.submit(run,args.root)
                last_bucket=bucket
            try:
                aggregate=start-last_aggregate>=300
                result=monitor(args.root,aggregate=aggregate)
                if aggregate:last_aggregate=start
                save(status,dict(pid=os.getpid(),state='RUNNING',at=result['at'],
                    monitoring_status=result['status'],evaluation_running=bool(future and not future.done()),mode='shadow'))
            except Exception as exc:
                save(status,dict(pid=os.getpid(),state='DEGRADED',at=datetime.now(timezone.utc).isoformat(),error=type(exc).__name__))
            if args.once:break
            stopping.wait(max(1,15-(time.monotonic()-start)))
    except KeyboardInterrupt:
        pass
    finally:
        pool.shutdown(wait=True,cancel_futures=True)
        save(status,dict(pid=os.getpid(),state='STOPPED',at=datetime.now(timezone.utc).isoformat()))
        for sig,handler in previous.items():signal.signal(sig,handler)
        guard.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
