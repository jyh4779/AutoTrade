import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock
from src.adapters.upbit.public import PublicAPI
from src.markets.crypto.strategy import POLICY,select_universe,evaluate,closed_bars


class Crypto(unittest.TestCase):
    def fixtures(self):
        now=datetime(2026,9,11,6,0,tzinfo=timezone.utc)
        bars=[dict(market='KRW-BTC',candle_date_time_utc=(now-timedelta(minutes=15*(26-i))).replace(tzinfo=None).isoformat(),
                   trade_price=100+i*.1,candle_acc_trade_volume=100) for i in range(26)]
        book=[dict(market='KRW-BTC',timestamp=now.timestamp()*1000,
                   orderbook_units=[dict(ask_price=103,bid_price=102.99,ask_size=100000,bid_size=100000)])]
        return now,bars,book

    def test_krw_only_and_warning_exclusion(self):
        markets=[dict(market=m,market_event=dict(warning=w,caution={}))
                 for m,w in [('KRW-BTC',False),('KRW-X',True),('BTC-ETH',False)]]
        tickers=[dict(market=m['market'],acc_trade_price_24h=2e9) for m in markets]
        selected,decisions=select_universe(markets,tickers,POLICY)
        self.assertEqual([x['symbol'] for x in selected],['KRW-BTC'])
        self.assertEqual(len(decisions),2)

    def test_incomplete_bar_is_excluded_and_gaps_rejected(self):
        now,bars,_=self.fixtures()
        incomplete=dict(bars[-1],candle_date_time_utc=now.replace(tzinfo=None).isoformat(),trade_price=999)
        self.assertEqual(closed_bars(bars+[incomplete],now)[-1]['trade_price'],102.5)
        with self.assertRaisesRegex(ValueError,'MISSING_CANDLE_INTERVAL'):
            closed_bars(bars[:12]+bars[13:],now)

    def test_spread_and_stale_book(self):
        now,bars,book=self.fixtures()
        result=evaluate(bars,book,'KRW-BTC',now,POLICY)
        self.assertAlmostEqual(result['score'],.4*result['trend']+.4*result['momentum']+.2*result['relative_volume'])
        book[0]['orderbook_units'][0]['ask_price']=105
        self.assertEqual(evaluate(bars,book,'KRW-BTC',now,POLICY)['reason'],'SPREAD_LIMIT')
        book[0]['timestamp']-=31000
        with self.assertRaisesRegex(ValueError,'STALE_ORDERBOOK'):
            evaluate(bars,book,'KRW-BTC',now,POLICY)

    def test_rate_limit_does_not_retry_storm(self):
        session=Mock();session.get.return_value.status_code=429
        with self.assertRaisesRegex(RuntimeError,'RATE_LIMITED'):
            PublicAPI(session).markets()
        self.assertEqual(session.get.call_count,1)

    def test_public_adapter_has_no_order_api(self):
        self.assertFalse(hasattr(PublicAPI,'submit'))
        self.assertFalse(hasattr(PublicAPI,'cancel'))
        with self.assertRaises(ValueError):PublicAPI.validate_symbol('USDT-BTC')
