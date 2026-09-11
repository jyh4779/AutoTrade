import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from datetime import datetime,timezone
from src.runners.crypto_daemon import monitor
from src.markets.crypto.research import Research


class Daemon(unittest.TestCase):
    def test_market_failure_still_monitors_existing_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ledger=Research(root/'data/crypto/upbit/data/research.db')
            now=datetime.now(timezone.utc).timestamp()
            def book(t,price):
                return dict(market='KRW-X',timestamp=t*1000,orderbook_units=[
                    dict(ask_price=price,bid_price=price,ask_size=100000,bid_size=100000)])
            ledger.signal('id','test','KRW-X',now-5000,.9,True,'test')
            ledger.advance('KRW-X',book(now-4999,100),now-4999,True)
            api=Mock();api.markets.side_effect=RuntimeError('offline')
            api.orderbook.return_value=[book(now,90)]
            result=monitor(root,api)
            self.assertEqual(result['orders_submitted'],0)
            self.assertEqual(ledger.feedback()['strategies']['test']['closed'],1)
            self.assertTrue(result['errors'])

    def test_monitor_reloads_persisted_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'data/crypto/upbit/data/research.db'
            ledger=Research(path)
            now=datetime.now(timezone.utc).timestamp()
            ledger.signal('id','test','KRW-X',now-10,.4,False,'score')
            self.assertIn('KRW-X',Research(path).watch_symbols(now))
