"""Usage: python -m src.runners.audit --date YYYY-MM-DD [--broker]. No orders."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from collections import Counter
from src.core.observability.events import EventStore, now_kst, ROOT
from src.markets.stocks.audit_checks import inspect


def observe_broker(store):
    from src.adapters.kis.kis_account import KISAccount
    data=KISAccount().get_balance()
    if data.get('rt_cd')!='0':
        store.emit('BROKER_OBSERVED',status='UNKNOWN',details='broker_query_failed')
        return
    broker={i['pdno']:int(i['hldg_qty']) for i in data.get('output1',[]) if int(i.get('hldg_qty',0))>0}
    path=store.root/'data/portfolio.db'
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:
            local=dict(c.execute('SELECT code,qty FROM holdings'))
        store.emit('BROKER_OBSERVED',status='PASS' if local==broker else 'FAIL',
                   details=dict(local=local,broker=broker))
    except Exception:
        store.emit('BROKER_OBSERVED',status='UNKNOWN',details='local_ledger_unavailable')


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--date',default=now_kst().date().isoformat())
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--broker',action='store_true')
    args=p.parse_args(argv)
    from datetime import date
    date.fromisoformat(args.date)
    store=EventStore(args.root)
    store.emit('AUDIT_STARTED',audit_day=args.date)
    if args.date == now_kst().date().isoformat():
        from src.core.observability.processes import watchdogs
        try:
            processes = watchdogs(args.root)
            store.emit('PROCESS_OBSERVED', processes=processes,
                       status='FAIL' if len(processes)>1 else 'PASS')
        except Exception as exc:
            store.emit('PROCESS_OBSERVED',processes=[],status='UNKNOWN',error_type=type(exc).__name__)
    if args.broker:
        if args.date!=now_kst().date().isoformat():
            p.error('--broker is only valid for the current trading date')
        observe_broker(store)
    findings=inspect(args.root,args.date)
    counts=Counter(f['status'] for f in findings)
    status='FAIL' if counts['FAIL'] else ('UNKNOWN' if counts['UNKNOWN'] else ('WARN' if counts['WARN'] else 'PASS'))
    report=dict(day=args.date,generated_at=now_kst().isoformat(),status=status,counts=dict(counts),
                performance_validation='NOT_ESTABLISHED',checks=findings)
    folder=args.root/'docs/audit';folder.mkdir(parents=True,exist_ok=True)
    target=folder/(args.date+'.json')
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)
    lines=[f'# Audit {args.date}',f'Status: {status}',f'Counts: {dict(counts)}',
           'Performance validation: NOT_ESTABLISHED','', '| Check | Status | Reason |','|---|---|---|']
    lines += [f"| {f['check_id']} | {f['status']} | {f['reason']} |" for f in findings]
    target.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')
    store.emit('AUDIT_FINISHED',audit_day=args.date,status=status,counts=dict(counts),report=str(target))
    store.export(args.date)
    print(json.dumps(dict(status=status,counts=dict(counts),report=str(target)),ensure_ascii=False))
    return 2 if status=='FAIL' else (3 if status=='UNKNOWN' else 0)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
