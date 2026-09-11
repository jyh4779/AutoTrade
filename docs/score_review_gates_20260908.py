import json,sys,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.trading.kis_auth import KISAuth
sys.stdout.reconfigure(encoding='utf-8')
OUT=ROOT/'docs/score_review_20260908_data'
rs=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
cache=json.loads((ROOT/'data/pre_analysis_cache.json').read_text(encoding='utf-8'))
ds=json.loads((ROOT/'docs/no_buy_review_20260908_data/daily.json').read_text(encoding='utf-8'))
target=OUT/'daily.json'
if target.exists():ds.update(json.loads(target.read_text(encoding='utf-8')))
a=KISAuth();headers=a.get_headers('FHKST03010100')
for r in rs:
    code=r['code']
    if r['day']=='20260908':prev=cache[code][-1]['Close']
    else:
        if code not in ds:
            for n in range(5):
                time.sleep(.8+n)
                z=requests.get(a.base_url+'/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice',headers=headers,
                    params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code,'FID_INPUT_DATE_1':'20260904',
                    'FID_INPUT_DATE_2':'20260908','FID_PERIOD_DIV_CODE':'D','FID_ORG_ADJ_PRC':'0'},timeout=20).json()
                if z.get('rt_cd')=='0':break
            if z.get('rt_cd')!='0':raise RuntimeError(z.get('msg_cd'))
            ds[code]=z['output2']
            target.write_text(json.dumps(ds,ensure_ascii=False,indent=2),encoding='utf-8')
        prev=float(next(b['stck_clpr'] for b in ds[code] if b['stck_bsop_date']=='20260904'))
    r['prev_close']=prev
    r['gap_pct']=100*(r['entry']/prev-1)
    r['price_ok']=r['entry']<=914313*.2
    r['gap_ok']=r['gap_pct']<=2
    r['drift_pct']=100*(r['entry']/r['screen_price']-1) if r.get('screen_price') else None
    if r['hold_net']>1 or (r.get('score') or 0)>=.6:
        print(r['day'],r['name'],'entry',r['entry'],'prev',prev,'gap',round(r['gap_pct'],3),'drift',r['drift_pct'],flush=True)
(OUT/'results_with_gates.json').write_text(json.dumps(rs,ensure_ascii=False,indent=2),encoding='utf-8')
print('COMPLETE')
