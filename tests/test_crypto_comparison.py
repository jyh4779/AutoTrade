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
