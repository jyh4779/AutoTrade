import tempfile
import unittest
from pathlib import Path
from src.markets.crypto.research import Research
from src.markets.crypto.strategy import select_universe,POLICY


class Feedback(unittest.TestCase):
    def test_temporal_split_excludes_overlapping_labels(self):
        from src.core.research.validation import temporal_split
        rows=[dict(signal_at=1,label_at=5),dict(signal_at=4,label_at=11),dict(signal_at=12,label_at=20)]
        train,test,excluded=temporal_split(rows,10,1)
        self.assertEqual((len(train),len(test),len(excluded)),(1,1,1))

    def test_labels_are_not_invented_before_horizon(self):
        with tempfile.TemporaryDirectory() as d:
            r=Research(Path(d)/'test.db')
            r.signal('id','base','KRW-X',100,.4,False,'score',reference=100)
            r.advance('KRW-X',self.book(101),101,False)
            self.assertEqual(r.feedback()['strategies']['base']['labelled_signals'],0)
            r.advance('KRW-X',self.book(3701),3701,False)
            self.assertEqual(r.feedback()['strategies']['base']['labelled_signals'],1)

    def book(self,at,price=100):
        return dict(market='KRW-X',timestamp=at*1000,orderbook_units=[
            dict(ask_price=price,bid_price=price,ask_size=100000,bid_size=100000)])

    def test_signal_is_not_filled_at_signal_time_or_twice(self):
        with tempfile.TemporaryDirectory() as d:
            r=Research(Path(d)/'test.db')
            r.signal('id','base','KRW-X',1000,.9,True,'candidate')
            self.assertEqual(r.advance('KRW-X',self.book(1000),1000,True),[])
            r.advance('KRW-X',self.book(1001),1001,True)
            r.advance('KRW-X',self.book(1002),1002,True)
            self.assertEqual(r.feedback()['strategies']['base']['open'],1)
            r.advance('KRW-X',self.book(4602),4602,True)
            result=r.feedback()['strategies']['base']
            self.assertEqual(result['closed'],1)
            self.assertEqual(float(result['realized_profit']),-100)

    def test_old_signal_and_market_block_never_enter(self):
        with tempfile.TemporaryDirectory() as d:
            r=Research(Path(d)/'test.db')
            r.signal('a','base','KRW-X',1,.9,True,'candidate')
            r.advance('KRW-X',self.book(1400),1400,True)
            r.signal('b','base','KRW-X',1400,.9,True,'candidate')
            r.advance('KRW-X',self.book(1401),1401,False)
            self.assertEqual(r.feedback()['strategies']['base']['open'],0)

    def test_liquidity_failure_does_not_fabricate_fill(self):
        with tempfile.TemporaryDirectory() as d:
            r=Research(Path(d)/'test.db')
            r.signal('a','base','KRW-X',100,.9,True,'candidate')
            book=self.book(101);book['orderbook_units'][0]['ask_size']=1
            with self.assertRaisesRegex(ValueError,'INSUFFICIENT_BOOK_DEPTH'):
                r.advance('KRW-X',book,101,True)
            self.assertEqual(r.feedback()['strategies']['base']['open'],0)

    def test_membership_does_not_override_warning(self):
        markets=[dict(market='KRW-X',market_event=dict(warning=True,caution={}))]
        selected,_=select_universe(markets,[dict(market='KRW-X',acc_trade_price_24h=2e9)],POLICY,{'KRW-X'})
        self.assertEqual(selected,[])
