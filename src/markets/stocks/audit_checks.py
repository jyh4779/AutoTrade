import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from src.core.observability.events import digest, release_hash, now_kst


def inspect(root, day, clock=None):
    root = Path(root)
    clock = clock or now_kst()
    findings = []

    def add(check, status, reason, evidence=None, **detail):
        findings.append(dict(check_id=check,status=status,reason=reason,evidence_ids=evidence or [],**detail))

    path = root/'data/audit.db'
    if not path.exists():
        add('OP-01','UNKNOWN','event_database_missing')
        return findings
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:
        events = [json.loads(r[0]) for r in c.execute('SELECT payload FROM events WHERE day=? ORDER BY seq',(day,))]
        snapshots = {r[0]:r[1] for r in c.execute('SELECT id,payload FROM snapshots')}
        starts = [json.loads(r[0]) for r in c.execute("SELECT payload FROM events WHERE kind='PROCESS_STARTED' AND day<=? ORDER BY seq",(day,))]
    if not events:
        add('OP-01','UNKNOWN','no_events_for_day')
        return findings
    group = defaultdict(list)
    by_id={e['event_id']:e for e in events}
    for e in events:
        group[e['event_type']].append(e)
        sid = e.get('snapshot_id')
        if sid:
            valid = sid in snapshots and digest(json.loads(snapshots[sid])) == sid
            add('DQ-04','PASS' if valid else 'FAIL','snapshot_integrity',[e['event_id']])
    for e in group['DATA_SNAPSHOT']:
        q=e['quote']
        dt=datetime.fromisoformat(e['event_time_utc'])-datetime.fromisoformat(q['received_at'])
        pday=(q.get('provider_date') or '').replace('-','')
        ok=-2<=dt.total_seconds()<=30 and (not pday or pday==day.replace('-','')) and e['history_date']<day
        add('DQ-01','PASS' if ok else 'FAIL','quote_and_history_time',[e['event_id']],age_seconds=dt.total_seconds())
        if not pday:
            add('DQ-02','WARN','provider_timestamp_absent_receipt_time_only',[e['event_id']])
    for e in group['TECH_COMPUTED']:
        expected=e['vol']*.3+e['sd']*.3+e['ts']*.4
        ok=math.isclose(expected,e['tech'],abs_tol=1e-10)
        if not e['pre_mode'] and not e['hard_filtered']:
            m=max(1.,e['elapsed_minutes'])
            f=max(.01,m*.2/30) if m<=30 else (.2+(m-30)*.5/300 if m<=330 else (.7+(m-330)*.3/60 if m<390 else 1.))
            expected_sd=min(e['volume']/f/e['average_volume']/2,1.)
            ok=ok and math.isclose(expected_sd,e['sd'],abs_tol=1e-10)
        add('SG-01','PASS' if ok else 'FAIL','independent_technical_calculation',[e['event_id']])
    for e in group['SCORE_COMPUTED']:
        w=e['weights']
        expected=e['tech']*w['tech_weight']+e['sentiment']*w['ai_weight']+e['fundamental']*w['fa_weight']
        add('SG-02','PASS' if math.isclose(expected,e['score'],abs_tol=1e-10) else 'FAIL',
            'independent_weighted_score',[e['event_id']],expected=expected,observed=e['score'])
    for e in group['SIGNAL_DECISION']:
        valid=(not e['selected'] or e['score']>=e['threshold'])
        if e['reason']=='SCORE_THRESHOLD':valid=valid and e['score']<e['threshold']
        add('SG-03','PASS' if valid else 'FAIL','entry_threshold_decision',[e['event_id']])
    for e in group['ENTRY_EVALUATED']:
        valid=e['qty']>0 and e['qty']*e['price']<=e['budget']+.001
        if e.get('screen_price'):valid=valid and e['price']/e['screen_price']<=1.015
        if e.get('prev_close'):valid=valid and e['price']/e['prev_close']<=1.02
        add('PF-03','PASS' if valid else 'FAIL','entry_budget_and_price_limits',[e['event_id']])
    if not group['SCORE_COMPUTED']:
        add('SG-02','N/A' if group['SCAN_COMPLETED'] or group['NO_TRADE_DECISION'] else 'UNKNOWN','no_score_evidence')
    for u in group['UNIVERSE_CREATED']:
        terminal=[e for e in group['FILTER_EVALUATED'] if e['scan_id']==u['scan_id']]
        counts=Counter(e['symbol'] for e in terminal)
        complete=any(e['scan_id']==u['scan_id'] for e in group['SCAN_COMPLETED'])
        ok=set(counts)==set(u['symbols']) and all(n==1 for n in counts.values())
        add('UN-01','PASS' if complete and ok else 'UNKNOWN' if not complete else 'FAIL',
            'universe_terminal_accounting',[u['event_id']],expected=len(u['symbols']),observed=len(terminal))
    for e in group['RISK_CHECKED']:
        allowed=(e['qty']>0 and e['qty']*e['price']<=e['cash']*e['ratio'] and
                 e['cash']-e['qty']*e['price']>=e['reserve'] and e['daily_buys']<e['max_daily_buys'])
        add('PF-01','PASS' if allowed==e['allowed'] else 'FAIL','independent_entry_limits',[e['event_id']])
    for e in group['ATOMIC_RISK_CHECK']:
        p=e['policy'];amount=e['qty']*e['price']
        valid=(amount<=e['basis_cash']*p['max_position_ratio'] and amount<=e['cash']-p['minimum_cash']
               and e['spent']+amount<=e['basis_cash']*p['max_gross_buy_ratio']
               and e['count']<e['max_daily_buys'] and e['realized_profit']>-e['basis_cash']*p['max_daily_loss_pct'])
        add('PF-02','PASS' if valid else 'FAIL','atomic_limits_recomputed',[e['event_id']])
    for e in group['ACCOUNT_RISK']:
        if 'basis_cash' not in e:
            add('RK-04','UNKNOWN','daily_account_basis_missing',[e['event_id']])
        else:
            breached=e['realized']+e['unrealized']<=-e['basis_cash']*e['limit_pct']
            add('RK-04','PASS' if breached==(e['status']=='FAIL') else 'FAIL','account_loss_calculation',[e['event_id']])
    for e in group['POSITION_MARKED']:
        ret=e['price']/e['average']-1 if e['average']>0 and e['price']>0 else None
        reason='INVALID_PRICE' if ret is None else ('TAKE_PROFIT' if ret>=e['target']-1e-12 else 'STOP_LOSS' if ret<=e['stop']+1e-12 else 'HOLD')
        add('RK-01','PASS' if reason==e['reason'] else 'FAIL','independent_exit_rule',[e['event_id']])
    for e in group['LIQUIDATION_CHECK']:
        status='UNKNOWN' if not e['confirmed'] else ('PASS' if not e['remaining'] and not e['pending_orders'] else 'WARN')
        add('RK-03',status,'liquidation_requires_broker_confirmation',[e['event_id']])
    for e in group['ACCOUNT_RECONCILED']:
        local={h['code']:h['qty'] for h in e['holdings']}
        broker={h['code']:h['qty'] for h in e['broker_holdings']}
        add('EX-04','PASS' if local==broker else 'FAIL','persisted_holdings_match_broker',[e['event_id']])
    # Latest independent external observation, not merely a sync routine's own success flag.
    if group['BROKER_OBSERVED']:
        e=group['BROKER_OBSERVED'][-1]
        add('EX-05',e['status'],'independent_broker_comparison',[e['event_id']],details=e.get('details'))
    else:
        add('EX-05','UNKNOWN','independent_broker_observation_missing')
    for expected in group['JOB_EXPECTED']:
        if expected['deadline']>clock.isoformat():
            continue
        name=expected['job_name']
        done=[e for e in group['JOB_FINISHED'] if e['job_name']==name]
        skipped=[e for e in group['JOB_SKIPPED'] if e['job_name']==name]
        historical=[e for e in group['JOB_BASELINE_UNKNOWN'] if e['job_name']==name]
        if done:
            add('OP-01','PASS' if done[-1]['returncode']==0 else 'FAIL','job_exit_status',[done[-1]['event_id']],job=name)
        elif skipped:
            add('OP-01','N/A' if skipped[-1]['reason']=='NON_TRADING_DAY' else 'WARN','job_skipped',[skipped[-1]['event_id']],job=name)
        elif historical:
            add('OP-01','UNKNOWN','job_precedes_instrumentation',[historical[-1]['event_id']],job=name)
        else:
            add('OP-01','FAIL','scheduled_job_missing',[expected['event_id']],job=name)
    if not group['JOB_EXPECTED']:
        add('OP-01','UNKNOWN','scheduler_expectations_not_observed')
    for started in group['AUDIT_STARTED']:
        completed=any(e['session_id']==started['session_id'] for e in group['AUDIT_FINISHED'])
        age=(clock-datetime.fromisoformat(started['event_time_utc'])).total_seconds()
        if not completed and age>180:
            add('OP-02','FAIL','audit_process_did_not_complete',[started['event_id']],age_seconds=age)
    latest={e['component']:e for e in starts}
    expected_hash=release_hash(root)
    for e in latest.values():
        add('CH-01','PASS' if e['code_version']==expected_hash else 'WARN','loaded_release_vs_disk',[e['event_id']],component=e['component'],started_at=e['event_time_utc'],
            process_scope='resident' if e['component'] in ('main_scheduler.py','watchdog.py') else 'job',
            liveness='NOT_INFERRED_FROM_START_EVENT')
    for component in ('main_scheduler.py','watchdog.py'):
        if component not in latest:
            add('CH-01','UNKNOWN','component_release_not_observed',component=component)
    if not group['CONFIG_LOADED']:
        add('CH-02','UNKNOWN','effective_configuration_not_observed')
    else:
        configs={e['component']:e for e in group['CONFIG_LOADED']}
        for e in configs.values():
            valid=digest(e['effective_config'])==e['effective_config_hash']
            add('CH-02','PASS' if valid else 'FAIL','effective_configuration_integrity',[e['event_id']])
    for gate in group['MARKET_GATE']:
        related=[e for e in group['ORDER_INTENT'] if e['run_id']==gate['run_id'] and e.get('side')=='BUY']
        ok=gate.get('allowed',False) or not related
        add('RK-04','PASS' if ok else 'FAIL','market_gate_orders',[gate['event_id']])
        if not gate.get('provider_time_verified',False):
            add('DQ-04','WARN','market_provider_time_unverified',[gate['event_id']])
    for pool in group['POOL_SELECTED']:
        add('UN-02','WARN' if pool['actual']<pool['target'] else 'PASS',
            'pool_target_coverage',[pool['event_id']],actual=pool['actual'],target=pool['target'])
    for failed in group['JOB_FINISHED']:
        if failed['returncode']!=0 and failed['job_name']!='Self Audit':
            recovered=any(e['job_name']==failed['job_name'] and e['returncode']==0
                and e['event_time_utc']>failed['event_time_utc'] for e in group['JOB_FINISHED'])
            if recovered:
                add('OP-03','WARN','job_failure_recovered',[failed['event_id']],job=failed['job_name'])
    portfolio=root/'data/portfolio.db'
    fills_observed=0
    if portfolio.exists():
        with sqlite3.connect(portfolio.as_uri()+'?mode=ro',uri=True) as c:
            c.row_factory=sqlite3.Row
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'managed_orders' in tables:
                for r in c.execute("SELECT * FROM managed_orders WHERE state IN ('SUBMITTING','UNKNOWN','ACK','PARTIAL')"):
                    add('EX-03','UNKNOWN','unresolved_order',intent_id=r['intent_id'],state=r['state'],age_since=r['created_at'])
                for r in c.execute('SELECT * FROM managed_orders WHERE day=?',(day,)):
                    fs=c.execute('SELECT COALESCE(SUM(qty),0),COALESCE(SUM(total),0) FROM managed_fills WHERE intent_id=?',(r['intent_id'],)).fetchone()
                    ok=fs[0]==r['filled_qty'] and abs(fs[1]-r['filled_total'])<=.01 and fs[0]<=r['requested_qty']
                    add('EX-02','PASS' if ok else 'FAIL','cumulative_fill_ledger',intent_id=r['intent_id'])
                    fills_observed+=fs[0]
            if 'trade_log' in tables:
                rows=c.execute("SELECT * FROM trade_log WHERE date LIKE ? AND type='SELL'",(day+'%',)).fetchall()
                known=[r for r in rows if r['profit'] is not None]
                add('BT-02','UNKNOWN' if len(known)!=len(rows) else ('PASS' if rows else 'N/A'),
                    'realized_pnl_ledger',net_profit=sum(r['profit'] for r in known),closed_fill_rows=len(rows),
                    win_rate=sum(r['profit']>0 for r in known)/len(known)*100 if known else None,
                    performance_validation='NOT_ESTABLISHED')
    if not fills_observed:
        add('EX-02','N/A','no_managed_live_fills_observed')
    if group['PROCESS_OBSERVED']:
        observation = group['PROCESS_OBSERVED'][-1]
        add('OP-04',observation['status'],'watchdog_process_count',[observation['event_id']],
            processes=observation['processes'])
        for process in observation['processes']:
            age=(clock-datetime.fromisoformat(process['last_activity'])).total_seconds()
            add('OP-05','WARN' if age>180 else 'PASS','watchdog_activity',
                [observation['event_id']],pid=process['pid'],age_seconds=age)
            add('OP-06','WARN' if process['version']!=release_hash(root) else 'PASS',
                'active_watchdog_version',[observation['event_id']],pid=process['pid'])
    for f in findings:
        f['execution_modes']=sorted({by_id[i]['execution_mode'] for i in f['evidence_ids'] if i in by_id})
    return findings
