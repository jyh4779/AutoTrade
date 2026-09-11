"""Read-only score audit. Uses historical log scores, never today's news scoring."""
import sys, json, re, time, io, zipfile
from pathlib import Path
from datetime import datetime, timedelta
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.trading.kis_auth import KISAuth
sys.stdout.reconfigure(encoding='utf-8')
OUT = ROOT / 'docs/score_review_20260908_data'
OUT.mkdir(exist_ok=True)
OLD = ROOT / 'docs/no_buy_review_20260908_data'
auth = KISAuth()
auth.auth()
session = requests.Session()

def query(endpoint, tr, params):
    for n in range(5):
        time.sleep(.7 + n)
        r = session.get(auth.base_url+'/uapi/domestic-stock/v1/quotations/'+endpoint,
                        headers=auth.get_headers(tr), params=params, timeout=20).json()
        if r.get('rt_cd') == '0':
            return r
        if r.get('msg_cd') != 'EGW00201':
            raise RuntimeError(str((r.get('msg_cd'),r.get('msg1'))))
    raise RuntimeError('rate limit retries exhausted')

master_path = OUT/'kospi_master.json'
if not master_path.exists():
    resp = session.get('https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip', timeout=30)
    resp.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    lines = z.read('kospi_code.mst').decode('cp949').splitlines(keepends=True)
    master = {line[:9].strip():line[21:-228].strip() for line in lines}
    master_path.write_text(json.dumps(master,ensure_ascii=False,indent=2),encoding='utf-8')
else:
    master = json.loads(master_path.read_text(encoding='utf-8'))

records = {}
for line in (ROOT/'data/scheduler.log').read_text(encoding='utf-8').splitlines():
    m = re.match(r'\[(2026-09-0[78]) (09:1[567]:\d\d)\]',line)
    if not m: continue
    day = m[1].replace('-','')
    c = re.search(r'([^>\[\]]+?) \((\d{6})\)',line)
    if not c: continue
    name, code = c[1].strip().lstrip('- '), c[2]
    if code not in master: continue
    r = records.setdefault((day,code),dict(day=day,code=code,name=name))
    t = re.search(r'TA ([\d.]+) \| SA (-?[\d.]+|N/A) \| FA ([\d.]+)',line)
    if t:
        r.update(ta=float(t[1]),sa=None if t[2]=='N/A' else float(t[2]),fa=float(t[3]))
        total = re.search(r'Total ([\d.]+)',line)
        if total: r['score']=float(total[1])
    t = re.search(r'TechScore ([\d.]+) \(Vol:([\d.]+), SD:([\d.]+), TS:([\d.]+)',line)
    if t: r.update(ta=float(t[1]),vol=float(t[2]),sd=float(t[3]),ts=float(t[4]))
    t = re.search(r'현재가:([\d,]+)',line)
    if t: r['screen_price']=int(t[1].replace(',',''))
    t = re.search(r'Price: ([\d,]+)',line)
    if t: r['screen_price']=int(t[1].replace(',',''))
    if '[SKIP]' in line: r['filter_reason']=line.split('): ',1)[-1]

# The current cache preserves Tuesday's complete pre-market universe, not Monday's.
for code in json.loads((ROOT/'data/pre_analysis_cache.json').read_text(encoding='utf-8')):
    if code in master:
        records.setdefault(('20260908',code),dict(day='20260908',code=code,name=master[code],filter_reason='morning log truncated; score unavailable'))

def bars_for(day,code):
    filename=f'{day}_{code}.json'
    for folder in (OLD,OUT):
        if (folder/filename).exists(): return json.loads((folder/filename).read_text(encoding='utf-8'))
    rows={};cursor='153000'
    for _ in range(6):
        p={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code,'FID_INPUT_DATE_1':day,
           'FID_INPUT_HOUR_1':cursor,'FID_PW_DATA_INCU_YN':'Y','FID_FAKE_TICK_INCU_YN':''}
        b=query('inquire-time-dailychartprice','FHKST03010230',p).get('output2',[])
        b=[x for x in b if x['stck_bsop_date']==day]
        if not b: break
        rows.update({x['stck_cntg_hour']:x for x in b})
        earliest=min(x['stck_cntg_hour'] for x in b)
        if earliest<='090000': break
        cursor=(datetime.strptime(earliest,'%H%M%S')-timedelta(minutes=1)).strftime('%H%M%S')
    result=sorted(rows.values(),key=lambda x:x['stck_cntg_hour'])
    (OUT/filename).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return result

results=[]
print('universe',len(records),flush=True)
for i,((day,code),r) in enumerate(sorted(records.items())):
    b=bars_for(day,code);by={x['stck_cntg_hour']:x for x in b}
    if '091700' not in by or '151000' not in by:
        r['data_error']='required minute missing';results.append(r);continue
    entry=float(by['091700']['stck_oprc']);end=float(by['151000']['stck_oprc'])
    path=[x for x in b if '091700'<=x['stck_cntg_hour']<'151000']
    exit_price=end;reason='time';ambiguous=False
    for x in path:
        op,hi,lo=[float(x[k]) for k in ['stck_oprc','stck_hgpr','stck_lwpr']]
        if op<=entry*.97: exit_price=op;reason='stop_gap';break
        if op>=entry*1.05: exit_price=op;reason='take_gap';break
        stop,take=lo<=entry*.97,hi>=entry*1.05
        if stop or take:
            ambiguous=stop and take;exit_price=entry*(.97 if stop else 1.05);reason='stop' if stop else 'take';break
    r.update(entry=entry,end=end,hold_net=100*(end*.99802/entry-1),rule_net=100*(exit_price*.99802/entry-1),
             reason=reason,ambiguous=ambiguous,max_return=100*(max(float(x['stck_hgpr']) for x in path)/entry-1))
    results.append(r)
    if i%8==0: print('progress',i+1,len(records),r['name'],round(r['hold_net'],2),flush=True)
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
df=pd.DataFrame(results)
df.to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
print('COMPLETE',len(df),'scored',df['score'].notna().sum(),flush=True)
print(df.sort_values('hold_net',ascending=False)[['day','name','ta','sa','fa','score','hold_net','rule_net','filter_reason']].head(25).to_string(index=False))
