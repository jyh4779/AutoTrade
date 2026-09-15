from src.markets.crypto.runtime import storage_path
"""Upbit public-data shadow evaluation. No credentials, balances, or order API."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from src.adapters.upbit.public import PublicAPI,error_details
from src.markets.crypto.strategy import POLICY,select_universe,evaluate,closed_bars,number
from src.core.observability.events import EventStore,ROOT,digest
from src.core.observability.processes import Singleton
from src.markets.crypto.research import Research
from src.markets.crypto.comparison import Comparison,active_comparison
from src.markets.crypto.experiments import challenger,EXPERIMENT


def run(root=ROOT, api=None):
    storage=storage_path(root)
    store=EventStore(storage,mode='shadow')
    api=api or PublicAPI()
    policy=dict(POLICY)
    scope=dict(asset_class='crypto',venue='upbit',quote_currency='KRW',
               account_alias='public',strategy_id=policy['strategy'])
    emit=lambda kind,**fields:store.emit(kind,required=True,**scope,**fields)
    emit('CRYPTO_STARTED',policy=policy,policy_hash=digest(policy))
    results=[]
    research=Research(storage/'data/research.db')
    comparison=active_comparison(storage)
    change=None
    try:
        markets=api.markets();tickers=api.tickers()
        received=datetime.now(timezone.utc).timestamp()
        tickers=[q for q in tickers if -5<=received-number(q.get('timestamp',0))/1000<=60]
        previous=research.observe_universe(tickers,received)
        selected,decisions=select_universe(markets,tickers,policy,previous)
        research.remember([x['symbol'] for x in selected],received)
        emit('CRYPTO_UNIVERSE',decisions=decisions,
             snapshot_id=store.snapshot(dict(markets=markets,tickers=tickers)))
        now=datetime.now(timezone.utc)
        try:
            btc=api.candles('KRW-BTC',now)
            bars=closed_bars(btc,now)
            change=number(bars[-1]['trade_price'])/number(bars[-5]['trade_price'])-1
            allowed=change>=policy['btc_hour_loss_limit']
            emit('CRYPTO_MARKET_GATE',allowed=allowed,hour_return=change,
                 snapshot_id=store.snapshot(btc))
        except Exception as exc:
            allowed=False
            emit('CRYPTO_MARKET_GATE',allowed=False,reason='DATA_UNAVAILABLE',**error_details(exc))
        selected_symbols={x['symbol'] for x in selected}
        monitoring=selected+[dict(symbol=s,name=s) for s in sorted(research.pending_symbols()-selected_symbols)]
        for item in monitoring:
            symbol=item['symbol']
            try:
                raw=api.candles(symbol,datetime.now(timezone.utc));book=api.orderbook(symbol)
                at=datetime.now(timezone.utc)
                snapshot=dict(symbol=symbol,candles=raw,orderbooks=book,at=at.isoformat(),policy=policy,btc_hour_return=change,experiment=EXPERIMENT)
                sid=store.snapshot(snapshot)
                actions=research.advance(symbol,book[0],at.timestamp(),allowed and symbol in selected_symbols)
                emit('CRYPTO_PAPER_ACTIONS',symbol=symbol,actions=actions)
                result=evaluate(raw,book,symbol,at,policy)
                replay=evaluate(snapshot['candles'],snapshot['orderbooks'],symbol,
                                datetime.fromisoformat(snapshot['at']),snapshot['policy'])
                arithmetic=.4*result['trend']+.4*result['momentum']+.2*result['relative_volume']
                result.update(name=item['name'],status='PASS',replay_match=replay==result,
                              arithmetic_valid=abs(arithmetic-result['score'])<1e-12)
                result['liquidity_history']=research.liquidity_history(symbol,at.timestamp())
                try:
                    experiment=challenger(raw,at,result,change)
                    result['experiment']=experiment
                except ValueError as exc:
                    result['experiment']=dict(status='UNKNOWN',reason=str(exc))
                closed=closed_bars(raw,at)
                bar=closed[-1]['candle_date_time_utc']
                liquid=result['reason'] not in ('SPREAD_LIMIT','DEPTH_FLOOR')
                variants=[(policy['strategy'],result['score'],policy['score_threshold'])]
                if 'score' in result['experiment']:
                    variants.append((EXPERIMENT['id'],result['experiment']['score'],EXPERIMENT['threshold']))
                for strategy,score,threshold in variants:
                    identity=digest([strategy,symbol,bar])
                    comparison.signal(identity,strategy,symbol,at.timestamp(),
                        allowed and liquid and symbol in selected_symbols and score>=threshold,result['reason'],score=score)
                    research.signal(identity,strategy,symbol,at.timestamp(),score,
                        allowed and liquid and symbol in selected_symbols and score>=threshold,
                        'MARKET_GATE' if not allowed else result['reason'],reference=book[0]['orderbook_units'][0]['ask_price'])
                emit('CRYPTO_EVALUATED',snapshot_id=sid,**result)
            except Exception as exc:
                result=dict(symbol=symbol,name=item['name'],status='UNKNOWN',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
                result['error_details']=error_details(exc)
                emit('CRYPTO_EVALUATED',**result)
            results.append(result)
        candidates=[r for r in results if r.get('eligible')]
        report=dict(generated_at=datetime.now(timezone.utc).isoformat(),execution_mode='shadow',
            universe_count=len(decisions),selected_count=len(selected),market_allows_entry=allowed,
            results=results,hypothetical_candidates=[r['symbol'] for r in candidates] if allowed else [],
            orders_submitted=0,performance_validation='NOT_ESTABLISHED')
        report['feedback']=research.feedback()
        report['status']='UNKNOWN' if not selected or any(r['status']=='UNKNOWN' for r in results) else 'PASS'
        if any(not r.get('replay_match',True) or not r.get('arithmetic_valid',True) for r in results):
            report['status']='FAIL'
        emit('CRYPTO_FINISHED',selected=len(selected),evaluated=len(results),orders_submitted=0)
        folder=storage/'reports';folder.mkdir(parents=True,exist_ok=True)
        out=folder/(store.run_id+'.json')
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        store.export(datetime.now().date().isoformat())
        return out,report
    except Exception as exc:
        emit('CRYPTO_FAILED',**error_details(exc))
        raise


def main():
    p=argparse.ArgumentParser(description='Upbit KRW public-data shadow evaluation; no orders')
    p.add_argument('--root',type=Path,default=ROOT)
    args=p.parse_args()
    guard=Singleton(storage_path(args.root),'crypto:upbit:shadow')
    if not guard.acquire():return 75
    try:
        out,report=run(args.root)
        print(json.dumps(dict(report=str(out),status=report['status'],selected=report['selected_count'],
            candidates=report['hypothetical_candidates'],orders_submitted=0),ensure_ascii=False))
    finally:
        guard.close()
    return 2 if report['status']=='FAIL' else 3 if report['status']=='UNKNOWN' else 0


if __name__=='__main__':
    raise SystemExit(main())
