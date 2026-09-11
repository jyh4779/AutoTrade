import gc
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.observability.events import EventStore, EmergencyStore, now_kst
from src.trading.strategy_logic import volume_score, technical_scores, combined_score, allocate, exit_reason
from src.trading.order_manager import OrderManager
from src.audit.checks import inspect
from src.research.replay import simulate_trade, replay_day


class Broker:
    def __init__(self):
        self.calls=0;self.response={'rt_cd':'0','output':{'ODNO':'001'}};self.detail=None
    def order_market_price(self,*args,**kwargs):
        self.calls+=1
        if isinstance(self.response,Exception):raise self.response
        return self.response
    def get_execution_detail(self,*args,**kwargs):return self.detail


class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.events=EventStore(self.root,mode='test')
        self.db=self.root/'data/portfolio.db'
        c=sqlite3.connect(self.db)
        c.executescript('''CREATE TABLE trade_log(id INTEGER PRIMARY KEY,date TEXT,type TEXT,code TEXT,name TEXT,
            qty INTEGER,price REAL,total REAL,profit REAL,return_pct REAL,score REAL);
            CREATE TABLE holdings(code TEXT PRIMARY KEY,name TEXT DEFAULT '',qty INTEGER,avg_price REAL);
            CREATE TABLE balance(id INTEGER PRIMARY KEY,amount REAL,updated_at TEXT);
            INSERT INTO balance VALUES(1,1000000,NULL);''');c.close()
        self.broker=Broker();self.orders=OrderManager(self.db,self.broker,self.events)
    def tearDown(self):
        gc.collect();self.tmp.cleanup()
    def count(self):
        c=sqlite3.connect(self.db);n=c.execute('SELECT COUNT(*) FROM trade_log').fetchone()[0];c.close();return n

    def test_actual_volume_not_prior_daily_volume(self):
        self.assertAlmostEqual(volume_score(100000,1000000,15),.5)
        self.assertEqual(volume_score(1000000,1000000,15),1.)
        with self.assertRaises(ValueError):volume_score(-1,100,15)
        with self.assertRaises(ValueError):volume_score(10,0,15)

    def test_weighted_score_and_boundary(self):
        w=dict(tech_weight=.55,ai_weight=.35,fa_weight=.1)
        self.assertAlmostEqual(combined_score(.7,0,.5,w),.435)
        with self.assertRaises(ValueError):combined_score(.7,None,.5,w)
        self.assertEqual(len(allocate([dict(score=.70)],900000,.70)),1)
        self.assertEqual(allocate([dict(score=.699999)],900000,.70),[])

    def test_exit_boundary(self):
        self.assertEqual(exit_reason(105,100),'TAKE_PROFIT')
        self.assertEqual(exit_reason(97,100),'STOP_LOSS')
        self.assertEqual(exit_reason(100,100),'HOLD')
        self.assertEqual(exit_reason(0,100),'INVALID_PRICE')

    def test_allocation_does_not_exceed_cash_or_cap(self):
        p=allocate([dict(score=.8),dict(score=.75),dict(score=.71)],914313,.7)
        self.assertLessEqual(sum(b for _,b in p),914313*.7)
        self.assertTrue(all(b<=914313*.2 for _,b in p))
        self.assertEqual(allocate([dict(score=.9)],99999,.7),[])

    def test_duplicate_intent_sends_once(self):
        a=self.orders.submit('000001','example',5,'BUY')
        b=self.orders.submit('000001','example',5,'BUY')
        self.assertEqual(a['intent_id'],b['intent_id']);self.assertEqual(self.broker.calls,1)

    def test_response_loss_survives_restart_without_resend(self):
        self.broker.response=TimeoutError()
        a=self.orders.submit('000001','example',5,'BUY')
        self.assertEqual(a['state'],'UNKNOWN');self.assertEqual(self.count(),0)
        restarted=OrderManager(self.db,self.broker,self.events)
        restarted.submit('000001','example',5,'BUY');restarted.reconcile()
        self.assertEqual(self.broker.calls,1)
        with self.assertRaises(ValueError):restarted.submit('000002','another',1,'BUY')

    def test_partial_cumulative_fills_are_idempotent(self):
        a=self.orders.submit('000001','example',5,'BUY')
        self.orders.apply_detail(a['intent_id'],dict(qty=2,total_amt=200))
        self.orders.apply_detail(a['intent_id'],dict(qty=2,total_amt=200))
        self.assertEqual(self.count(),1)
        self.assertEqual(self.orders.get(a['intent_id'])['state'],'PARTIAL')
        self.orders.apply_detail(a['intent_id'],dict(qty=5,total_amt=515))
        c=sqlite3.connect(self.db);rows=c.execute('SELECT qty,total FROM trade_log ORDER BY id').fetchall();c.close()
        self.assertEqual(rows,[(2,200.),(3,315.)]);self.assertEqual(self.orders.get(a['intent_id'])['state'],'FILLED')
        self.assertEqual(self.orders.pending(),[])

    def test_overfill_rejected_without_corrupting_ledger(self):
        a=self.orders.submit('000001','example',5,'BUY')
        with self.assertRaises(ValueError):self.orders.apply_detail(a['intent_id'],dict(qty=6,total_amt=600))
        self.assertEqual(self.count(),0)

    def test_cancel_partial_does_not_invent_remaining_fill(self):
        a=self.orders.submit('000001','example',5,'BUY')
        self.orders.apply_detail(a['intent_id'],dict(qty=2,total_amt=200,cancelled=True))
        self.assertEqual(self.orders.get(a['intent_id'])['state'],'CANCELLED');self.assertEqual(self.count(),1)

    def test_unconfirmed_fill_does_not_use_current_price(self):
        self.orders.submit('000001','example',5,'BUY');self.orders.reconcile()
        self.assertEqual(self.count(),0)
        checks=inspect(self.root,now_kst().date().isoformat())
        self.assertTrue(any(c['check_id']=='EX-03' and c['status']=='UNKNOWN' for c in checks))

    def test_sell_pnl_unknown_when_basis_unknown(self):
        a=self.orders.submit('000001','example',2,'SELL')
        self.orders.apply_detail(a['intent_id'],dict(qty=2,total_amt=200))
        c=sqlite3.connect(self.db);profit=c.execute('SELECT profit FROM trade_log').fetchone()[0];c.close()
        self.assertIsNone(profit)

    def test_sell_cumulative_fee_rounding(self):
        a=self.orders.submit('000001','example',2,'SELL',cost_basis=1000)
        self.orders.apply_detail(a['intent_id'],dict(qty=1,total_amt=1200))
        self.orders.apply_detail(a['intent_id'],dict(qty=2,total_amt=2400))
        c=sqlite3.connect(self.db);profit=c.execute('SELECT SUM(profit) FROM trade_log').fetchone()[0];c.close()
        self.assertEqual(profit,396.)

    def test_missing_logs_are_not_pass(self):
        checks=inspect(self.root,'2000-01-01')
        self.assertEqual(checks[0]['status'],'UNKNOWN')

    def test_audit_detects_wrong_score(self):
        self.events.emit('SCORE_COMPUTED',tech=.7,sentiment=0,fundamental=.5,
                         weights=dict(tech_weight=.55,ai_weight=.35,fa_weight=.1),score=.99)
        checks=inspect(self.root,now_kst().date().isoformat())
        self.assertTrue(any(c['check_id']=='SG-02' and c['status']=='FAIL' for c in checks))

    def test_missing_candidate_terminal_is_failure(self):
        self.events.emit('UNIVERSE_CREATED',scan_id='s',symbols=['a','b'])
        self.events.emit('FILTER_EVALUATED',scan_id='s',symbol='a',outcome='REJECT')
        self.events.emit('SCAN_COMPLETED',scan_id='s')
        self.assertTrue(any(c['check_id']=='UN-01' and c['status']=='FAIL' for c in inspect(self.root,now_kst().date().isoformat())))

    def test_snapshot_tampering_detected(self):
        sid=self.events.snapshot(dict(price=10));self.events.emit('DATA_TEST',snapshot_id=sid)
        with self.events.connect() as c:c.execute('UPDATE snapshots SET payload=? WHERE id=?',('{"price":20}',sid))
        self.assertTrue(any(c['check_id']=='DQ-04' and c['status']=='FAIL' for c in inspect(self.root,now_kst().date().isoformat())))

    def test_emergency_store_blocks_buys_but_allows_exit_evidence(self):
        events=EmergencyStore(self.root)
        with self.assertRaises(RuntimeError):events.emit('ORDER_INTENT',required=True)
        events.emit('EXIT_PENDING',symbol='000001')
        self.assertTrue((self.root/'log/emergency.jsonl').exists())

    def test_shadow_cannot_submit(self):
        self.events.mode='shadow'
        with self.assertRaises(ValueError):self.orders.submit('000001','example',1,'BUY')
        self.assertEqual(self.broker.calls,0)

    def test_secrets_are_removed(self):
        sid=self.events.snapshot(dict(app_key='secret',nested=dict(access_token='hidden',price=10)))
        with self.events.connect() as c:text=c.execute('SELECT payload FROM snapshots WHERE id=?',(sid,)).fetchone()[0]
        self.assertNotIn('secret',text);self.assertNotIn('hidden',text)

    def test_ambiguous_bar_does_not_assume_profit(self):
        bars=[dict(stck_cntg_hour='091700',stck_oprc='100',stck_hgpr='106',stck_lwpr='96'),
              dict(stck_cntg_hour='151000',stck_oprc='104')]
        self.assertEqual(simulate_trade(bars)['status'],'UNKNOWN')

    def test_stop_precedes_later_gain(self):
        bars=[dict(stck_cntg_hour='091700',stck_oprc='100',stck_hgpr='101',stck_lwpr='96'),
              dict(stck_cntg_hour='151000',stck_oprc='110')]
        r=simulate_trade(bars);self.assertEqual(r['reason'],'STOP_LOSS');self.assertLess(r['net_return'],0)

    def test_technical_replay_uses_saved_input(self):
        history=[dict(Open=100,High=101,Low=99,Close=100,Volume=1000000,Vol_MA5=1000000,RSI=50,MA20=99) for _ in range(20)]
        w=dict(tech_weight=.55,ai_weight=.35,fa_weight=.1,score_threshold=.7)
        q=dict(price=102,cumulative_volume=100000,received_at=now_kst().isoformat())
        t=technical_scores(history,102,100000,15,w)
        self.assertAlmostEqual(t['sd'],.5);self.assertAlmostEqual(t['ts'],.6)
        self.events.emit('CONFIG_LOADED',component='screener',effective_config=w,effective_config_hash='not_relevant')
        sid=self.events.snapshot(dict(history=history,quote=q))
        self.events.emit('DATA_SNAPSHOT',scan_id='s',symbol='x',snapshot_id=sid,quote=q,history_date='2000-01-01')
        self.events.emit('TECH_COMPUTED',scan_id='s',symbol='x',pre_mode=False,volume=100000,elapsed_minutes=15,tech=t['vol']*.3+t['sd']*.3+t['ts']*.4)
        self.assertEqual(replay_day(self.root,now_kst().date().isoformat())[0]['status'],'PASS')

    def test_atomic_limit_rechecked_after_another_order(self):
        risk=dict(cash=1000000,price=100000,max_daily_buys=1)
        a=self.orders.submit('000001','one',1,'BUY',risk_context=risk)
        self.orders.apply_detail(a['intent_id'],dict(qty=1,total_amt=100000))
        with self.assertRaises(ValueError):self.orders.submit('000002','two',1,'BUY',risk_context=risk)
        self.assertEqual(self.broker.calls,1)

    def test_account_loss_blocks_further_entry(self):
        risk=dict(cash=1000000,price=100000,max_daily_buys=3)
        a=self.orders.submit('000001','one',1,'BUY',risk_context=risk)
        self.orders.apply_detail(a['intent_id'],dict(qty=1,total_amt=100000))
        self.assertTrue(self.orders.check_account_loss(-20000))
        with self.assertRaises(ValueError):self.orders.submit('000002','two',1,'BUY',risk_context=risk)

    def test_cancel_response_loss_is_not_retried(self):
        a=self.orders.submit('000001','one',5,'BUY')
        self.broker.get_cancelable_order=lambda *args:dict(qty=5,orgno='x',order_no='001')
        calls=[]
        def cancel(p):calls.append(p);raise TimeoutError()
        self.broker.cancel_order=cancel
        self.assertFalse(self.orders.cancel_pending(a['intent_id']))
        self.assertFalse(self.orders.cancel_pending(a['intent_id']))
        self.assertEqual(len(calls),1)
        self.assertEqual(self.orders.get(a['intent_id'])['state'],'ACK')

    def test_cancel_ack_waits_for_confirmed_broker_state(self):
        a=self.orders.submit('000001','one',5,'BUY')
        self.broker.get_cancelable_order=lambda *args:dict(qty=5,orgno='x',order_no='001')
        self.broker.cancel_order=lambda preview:dict(rt_cd='0')
        self.broker.detail=dict(qty=2,total_amt=200,cancelled=True)
        self.assertTrue(self.orders.cancel_pending(a['intent_id']))
        self.assertEqual(self.count(),1)

    def test_live_trader_never_fabricates_unconfirmed_buy(self):
        from src.trading.kis_trader import KISTrader
        bot=KISTrader.__new__(KISTrader)
        bot.db_path=str(self.db);bot.events=self.events;bot.orders=self.orders;bot.domestic=self.broker
        self.broker.get_current_quote=lambda code:dict(price=100000)
        class Account:
            def get_balance(self):return dict(rt_cd='0',output1=[],output2=[dict(dnca_tot_amt='1000000')])
        bot.account=Account()
        with patch('src.trading.kis_trader.time.sleep'),patch('src.trading.strategy_manager.StrategyManager') as manager:
            manager.return_value.get_weights.return_value={'max_daily_buys':3}
            self.assertFalse(bot.buy('000001','one',1,.8))
        self.assertEqual(self.count(),0)
        self.assertEqual(self.broker.calls,1)

    def test_missing_job_after_deadline_is_detected(self):
        self.events.emit('JOB_EXPECTED',job_name='Morning Routine',deadline='2000-01-01T10:00:00+09:00')
        self.assertTrue(any(c['check_id']=='OP-01' and c['status']=='FAIL' for c in inspect(self.root,now_kst().date().isoformat())))

    def test_screener_records_complete_rejection_for_stale_history(self):
        import pandas as pd
        from src.trading.morning_screener import MorningScreener
        s=MorningScreener.__new__(MorningScreener)
        history=[dict(Open=100,High=105,Low=95,Close=100,Volume=1000000,Vol_MA5=1000000,RSI=50,MA20=99) for _ in range(20)]
        s.stocks={'000001':pd.DataFrame(history)};s.names={'000001':'one'};s.pre_data={'000001':history}
        s.weights={};s.events=self.events;s.pre_mode=False;s.scan_id='integration';s.cache_path=str(self.root/'cache.json')
        Path(s.cache_path).write_text('{}');s.max_price=200;s.min_atr_pct=.045
        with patch('src.trading.morning_screener.KISDomestic') as domestic:
            domestic.return_value.get_current_quote.return_value=dict(price=102,cumulative_volume=100000,received_at=now_kst().isoformat())
            s.scan_tech()
        self.assertEqual(s.candidates,[])
        findings=inspect(self.root,now_kst().date().isoformat())
        self.assertTrue(any(c['check_id']=='UN-01' and c['status']=='PASS' for c in findings))


if __name__=='__main__':unittest.main()
