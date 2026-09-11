"""Read-only market-data review; never imports or calls order methods."""
import sys
import re
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.trading.kis_auth import KISAuth

sys.stdout.reconfigure(encoding='utf-8')
OUT = ROOT / 'docs' / 'no_buy_review_20260908_data'
OUT.mkdir(exist_ok=True)
auth = KISAuth()
session = requests.Session()
headers = auth.get_headers('FHKST03010230')

def fetch(code, day):
    path = OUT / f'{day}_{code}.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    rows = {}
    cursor = '153000'
    for _ in range(6):
        params = {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
                  'FID_INPUT_HOUR_1': cursor, 'FID_INPUT_DATE_1': day,
                  'FID_PW_DATA_INCU_YN': 'Y', 'FID_FAKE_TICK_INCU_YN': ''}
        for attempt in range(5):
            time.sleep(.65 + attempt)
            r = session.get(auth.base_url + '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice',
                            headers=headers, params=params, timeout=20).json()
            if r.get('msg_cd') != 'EGW00201':
                break
        if r.get('rt_cd') != '0':
            raise RuntimeError(str((r.get('msg_cd'), r.get('msg1'))))
        batch = [b for b in r.get('output2', []) if b['stck_bsop_date'] == day]
        if not batch:
            break
        for b in batch:
            rows[b['stck_cntg_hour']] = b
        earliest = min(b['stck_cntg_hour'] for b in batch)
        if earliest <= '090000':
            break
        cursor = (datetime.strptime(earliest, '%H%M%S') - timedelta(minutes=1)).strftime('%H%M%S')
        time.sleep(.15)
    result = sorted(rows.values(), key=lambda b: b['stck_cntg_hour'])
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result

pattern = re.compile(r'\[(2026-09-0[78]) (\d\d:\d\d:\d\d)\] (\d)\. (.*?) \((\d+)\) \| Score: ([\d.]+) \| Price: ([\d,]+) KRW')
picks = []
for m in pattern.finditer((ROOT / 'data/scheduler.log').read_text(encoding='utf-8')):
    day, stamp, rank, name, code, score, price = m.groups()
    picks.append(dict(day=day, signal_time=stamp, rank=int(rank), name=name, code=code,
                      score=float(score), screen_price=int(price.replace(',', ''))))

results = []
for p in picks:
    bars = fetch(p['code'], p['day'].replace('-', ''))
    by_time = {b['stck_cntg_hour']: b for b in bars}
    assert all(t in by_time for t in ['091700', '151000']), (p, 'missing required bars')
    # First full minute after the signal; open is an executable-price proxy.
    entry = float(by_time['091700']['stck_oprc'])
    end = float(by_time['151000']['stck_oprc'])
    path = [b for b in bars if '091700' <= b['stck_cntg_hour'] < '151000']
    exit_price, exit_time, reason = end, '151000', 'time'
    ambiguous = False
    for b in path:
        op, hi, lo = (float(b[k]) for k in ['stck_oprc', 'stck_hgpr', 'stck_lwpr'])
        if op <= entry * .97:
            exit_price, exit_time, reason = op, b['stck_cntg_hour'], 'stop_gap'
            break
        if op >= entry * 1.05:
            exit_price, exit_time, reason = op, b['stck_cntg_hour'], 'take_gap'
            break
        stop, take = lo <= entry * .97, hi >= entry * 1.05
        if stop or take:
            ambiguous = stop and take
            exit_price = entry * (.97 if stop else 1.05)
            exit_time, reason = b['stck_cntg_hour'], 'stop' if stop else 'take'
            break
    qty = int(914313 * .2 // entry)
    r = dict(**p, entry=entry, end_1510=end, close_1530=float(by_time['153000']['stck_prpr']) if '153000' in by_time else None,
             min_return=100*(min(float(b['stck_lwpr']) for b in path)/entry-1),
             max_return=100*(max(float(b['stck_hgpr']) for b in path)/entry-1),
             exit_price=exit_price, exit_time=exit_time, reason=reason, ambiguous=ambiguous,
             net_return=100*(exit_price*.99802/entry-1), hold_net_return=100*(end*.99802/entry-1),
             qty=qty, net_profit=qty*(exit_price*.99802-entry),
             drift_pct=100*(entry/p['screen_price']-1), bar_count=len(bars))
    results.append(r)
    print(json.dumps(r, ensure_ascii=False), flush=True)
(OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
