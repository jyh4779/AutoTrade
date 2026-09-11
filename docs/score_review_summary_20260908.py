import json,sys
from pathlib import Path
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/score_review_20260908_data'
df=pd.read_json(OUT/'results.json',dtype={'day':str,'code':str})
df['code']=df['code'].str.zfill(6)
scored=df.dropna(subset=['ta','sa','fa','score','hold_net']).copy()
eligible=scored[scored.fa>=.4].copy()
print('COUNTS',df.groupby('day').size().to_dict(),'fully_scored',len(scored),'FA_eligible',len(eligible))
print('WINNERS')
print(df[df.hold_net>0].sort_values('hold_net',ascending=False)[['day','name','ta','sa','fa','score','hold_net','rule_net','filter_reason']].to_string(index=False))
print('SCORED ALL')
print(scored[['day','name','ta','sa','fa','score','hold_net','rule_net']].to_string(index=False))
print('DESCRIPTIVE CORRELATIONS')
for day,part in [('all',eligible)]+list(eligible.groupby('day')):
    print(day,len(part),part[['ta','sa','fa','score','hold_net']].corr(method='spearman')['hold_net'].to_dict())

variants={'current':(.55,.35,.10),'tech65':(.65,.25,.10),'tech70':(.70,.20,.10),
          'sentiment55':(.35,.55,.10),'FA20':(.50,.30,.20)}
summaries=[]
for label,weights in variants.items():
    d=eligible.copy()
    d['new_score']=sum(d[k]*w for k,w in zip(['ta','sa','fa'],weights))
    # Same threshold, maximum three selected per day; ranking uses rounded historical inputs.
    picks=d[d.new_score>=.70].sort_values(['day','new_score'],ascending=[True,False]).groupby('day').head(3)
    border=d[(d.new_score-.70).abs()<=.0050001]
    res=dict(label=label,weights=weights,count=len(picks),mean_hold=float(picks.hold_net.mean()) if len(picks) else None,
             mean_rule=float(picks.rule_net.mean()) if len(picks) else None,
             picks=picks[['day','name','new_score','hold_net','rule_net']].to_dict('records'),
             borderline=border[['day','name','new_score']].to_dict('records'))
    summaries.append(res)
    print('VARIANT',json.dumps(res,ensure_ascii=False))

# Tuesday cache confirms the input to the live SD calculation is prior-day volume.
cache=json.loads((ROOT/'data/pre_analysis_cache.json').read_text(encoding='utf-8'))
vol=[]
for code,history in cache.items():
    path=OUT/f'20260908_{code}.json'
    if not path.exists():path=ROOT/f'docs/no_buy_review_20260908_data/20260908_{code}.json'
    if not path.exists():continue
    bars=json.loads(path.read_text(encoding='utf-8'))
    cumulative=sum(int(b['cntg_vol']) for b in bars if '090000'<=b['stck_cntg_hour']<'091500')
    ma=float(history[-1]['Vol_MA5'])
    if ma<=0:continue
    old=min(float(history[-1]['Volume'])/.1/ma/2,1)
    corrected=min(cumulative/.1/ma/2,1)
    match=df[(df.day=='20260908')&(df.code==code)]
    vol.append(dict(code=code,name=match.iloc[0]['name'] if len(match) else code,old_sd=old,actual_volume_sd=corrected,
                    cumulative_0915=cumulative,prior_daily_volume=history[-1]['Volume']))
print('VOLUME',len(vol),'old saturated',sum(x['old_sd']==1 for x in vol),'actual saturated',sum(x['actual_volume_sd']==1 for x in vol))
print(pd.DataFrame(vol).sort_values('actual_volume_sd').head(12).to_string(index=False))
(OUT/'summary.json').write_text(json.dumps(dict(variants=summaries,volume=vol),ensure_ascii=False,indent=2),encoding='utf-8')
