import tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import Mock
from src.markets.crypto.comparison import Comparison,BASE,EXPERIMENT
from src.markets.crypto.execution_profile import ExecutionProfile
from src.markets.crypto.live_orders import LiveOrders

class ComparisonTests(unittest.TestCase):
    def book(self,t,size=100000,price=100):
        return dict(market='KRW-X',timestamp=t*1000,orderbook_units=[dict(ask_price=price,bid_price=price,ask_size=size,bid_size=size)])

    def test_shared_prices_fees_and_delayed_fill(self):
        with tempfile.TemporaryDirectory() as d:
            r=Comparison(Path(d)/'paper.db')
            for s in (BASE,EXPERIMENT):r.signal(s,s,'KRW-X',100,True,'ENTRY')
            self.assertEqual(r.observe('KRW-X',self.book(101),101,True),[])
            events=r.observe('KRW-X',self.book(102),102,True)
            self.assertEqual(len(events),2)
            self.assertEqual(events[0]['observation_id'],events[1]['observation_id'])
            self.assertEqual(r.observe('KRW-X',self.book(102),102,True),[])
            r.observe('KRW-X',self.book(3703),3703,True)
            r.observe('KRW-X',self.book(3704),3704,True)
            report=r.report()
            for lane in report['lanes'].values():
                self.assertEqual(lane['realized_profit'],'-100.0000')
                self.assertEqual(lane['open_positions'],0)

    def test_partial_fill_and_profile_cannot_mutate_history(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'paper.db';r=Comparison(path)
            r.signal('s',BASE,'KRW-X',100,True,'ENTRY')
            r.observe('KRW-X',self.book(101),101,True)
            events=r.observe('KRW-X',self.book(102,size=1),102,True)
            self.assertTrue(events[0]['partial'])
            with r.connect() as c:self.assertEqual(c.execute('select qty from positions').fetchone()[0],'1')
            with self.assertRaisesRegex(ValueError,'PROFILE_CHANGE'):
                Comparison(path,replace(ExecutionProfile(),buy_fee='.001'))

    def test_live_disabled_and_experiment_cannot_submit(self):
        with tempfile.TemporaryDirectory() as d:
            api=Mock();r=LiveOrders(Path(d)/'live.db',api)
            with self.assertRaisesRegex(ValueError,'DISABLED'):r.submit('s',BASE,'KRW-X','BUY','10000')
            r.enabled=True
            with self.assertRaisesRegex(ValueError,'FORBIDDEN'):r.submit('s',EXPERIMENT,'KRW-X','BUY','10000')
            api.submit.assert_not_called()

    def test_unknown_submission_is_reconciled_without_resubmit(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'live.db';api=Mock();api.submit.side_effect=TimeoutError()
            r=LiveOrders(path,api,True,'100000')
            with self.assertRaises(TimeoutError):r.submit('s',BASE,'KRW-X','BUY','10000')
            r=LiveOrders(path,api,True,'100000')
            identifier=r.submit('s',BASE,'KRW-X','BUY','10000')
            self.assertEqual(api.submit.call_count,1)
            api.order.return_value=dict(identifier=identifier,state='cancel',executed_volume='1',paid_fee='5')
            self.assertEqual(r.reconcile(),1)
            with r.connect() as c:
                self.assertEqual(c.execute('select state from orders').fetchone()[0],'cancel')

    def test_private_jwt_signature_and_query_hash(self):
        import base64,json,hmac,hashlib
        from src.adapters.upbit.private import PrivateAPI
        api=PrivateAPI('test-access','test-secret',session=Mock())
        token=api._token({'identifier':'abc'})
        head,body,signature=token.split('.')
        decode=lambda s:base64.urlsafe_b64decode(s+'='*(-len(s)%4))
        self.assertEqual(json.loads(decode(body))['query_hash'],hashlib.sha512(b'identifier=abc').hexdigest())
        self.assertEqual(decode(signature),hmac.new(b'test-secret',(head+'.'+body).encode(),hashlib.sha512).digest())

    def test_paper_runner_does_not_import_private_order_adapter(self):
        import subprocess,sys
        code="import src.runners.crypto_daemon,sys; assert 'src.adapters.upbit.private' not in sys.modules; assert 'src.markets.crypto.live_orders' not in sys.modules"
        subprocess.run([sys.executable,'-c',code],check=True)

    def test_score_tier_boundaries(self):
        from src.markets.crypto.execution_profile import score_profile
        p=score_profile()
        for score,amount in [('.6499',0),('.65',100000),('.7499',100000),('.75',150000),('.8499',150000),('.85',200000),('1',200000)]:
            self.assertEqual(p.buy_amount(score),amount)
        for score in ('NaN','Infinity','-1','1.01'):
            with self.assertRaises(ValueError):p.buy_amount(score)
        self.assertIsNone(p.daily_loss_limit)

    def test_score_amount_persisted_and_fee_reserved(self):
        from src.markets.crypto.execution_profile import score_profile
        with tempfile.TemporaryDirectory() as d:
            r=Comparison(Path(d)/'v2.db',score_profile())
            r.signal('a',BASE,'KRW-X',100,True,'ENTRY',score='.85')
            r.signal('b',EXPERIMENT,'KRW-X',100,True,'ENTRY',score='.75')
            r.observe('KRW-X',self.book(101),101,True)
            r.observe('KRW-X',self.book(102),102,True)
            with r.connect() as c:
                amounts={row['strategy']:(float(row['cost']),float(row['fee'])) for row in c.execute('select * from positions')}
            self.assertEqual(amounts[BASE],(200000,100))
            self.assertEqual(amounts[EXPERIMENT],(150000,75))

    def test_scored_live_buy_requires_fee_inclusive_capital(self):
        with tempfile.TemporaryDirectory() as d:
            r=LiveOrders(Path(d)/'live.db',Mock(),True,'200000')
            r.submit=Mock(return_value='intent')
            self.assertEqual(r.submit_scored_buy('s',BASE,'KRW-X','.85','1000000','0','.0005'),'intent')
            self.assertEqual(r.submit.call_args.args[-1],200000)
            for cash,committed in [('200000','0'),('1000000','800000')]:
                with self.assertRaisesRegex(ValueError,'CAPITAL_LIMIT'):
                    r.submit_scored_buy('s',BASE,'KRW-X','.85',cash,committed,'.0005')

    def test_retired_lane_cancels_pending_buy(self):
        with tempfile.TemporaryDirectory() as d:
            r=Comparison(Path(d)/'old.db')
            r.signal('s',BASE,'KRW-X',100,True,'ENTRY')
            r.observe('KRW-X',self.book(101),101,True)
            r.observe('KRW-X',self.book(102),102,False)
            with r.connect() as c:
                self.assertEqual(c.execute('select state from orders').fetchone()[0],'CANCELLED')
                self.assertEqual(c.execute('select count(*) from positions').fetchone()[0],0)
