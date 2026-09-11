import unittest
from unittest.mock import Mock, patch
import pandas as pd
from src.trading.morning_screener import MorningScreener


class KospiUniverse(unittest.TestCase):
    def test_blocked_market_never_enters_order_loop(self):
        from src.trading import auto_trade_main as main
        events = Mock(mode='test')
        bot = Mock()
        bot.get_holdings.return_value = []
        bot.orders.pending.return_value = []
        bot.get_balance.return_value = 1000000
        screener = Mock(entry_allowed=False, market_weak=False, scan_id='test')
        screener.run.return_value = [{'code':'005930','name':'test','score':0.9}]
        with patch.object(main,'audit',return_value=events), \
             patch.object(main,'get_trader',return_value=bot), \
             patch.object(main,'MorningScreener',return_value=screener), \
             patch.object(main,'get_dynamic_threshold',return_value=0.7), \
             patch('src.utils.market_calendar.require_trading_day',return_value=True):
            main.run_auto_trade()
        screener.run.assert_called_once()
        bot.buy.assert_not_called()
        bot.get_current_price.assert_not_called()

    def test_market_decline_still_evaluates(self):
        screener = MorningScreener.__new__(MorningScreener)
        screener.check_market_pulse = Mock(return_value=False)
        screener.load_data = Mock()
        screener.scan_tech = Mock()
        screener.candidates = []
        screener.run()
        screener.load_data.assert_called_once()
        screener.scan_tech.assert_called_once()

    def test_market_gate_only_uses_kospi_and_rejects_stale_data(self):
        from src.observability.events import now_kst
        screener = MorningScreener.__new__(MorningScreener)
        screener.events = Mock()
        screener.scan_id = 'test'
        frame = pd.DataFrame({'등락률': [-0.69]}, index=pd.to_datetime([now_kst().date()]))
        with patch('src.trading.morning_screener.stock.get_market_ohlcv_by_date', return_value=frame) as fetch:
            self.assertTrue(screener.check_market_pulse())
            self.assertTrue(screener.market_weak)
            self.assertEqual(fetch.call_count, 1)
            frame.iloc[0, 0] = -2.09
            self.assertFalse(screener.check_market_pulse())
            frame.index = pd.to_datetime(['2000-01-01'])
            self.assertFalse(screener.check_market_pulse())

    def test_kis_only_requests_kospi(self):
        screener = MorningScreener.__new__(MorningScreener)
        screener._fetch_kis_volume_page = Mock(return_value=(['005930'], ''))
        with patch('src.trading.morning_screener.KISAuth') as auth:
            auth.return_value.get_token.return_value = 'test'
            auth.return_value.config = {}
            self.assertEqual(screener._get_kis_volume_rank_paginated(), ['005930'])
        self.assertEqual(screener._fetch_kis_volume_page.call_count, 1)
        self.assertEqual(screener._fetch_kis_volume_page.call_args.args[3], '0001')

    def test_secondary_rank_only_requests_kospi(self):
        screener = MorningScreener.__new__(MorningScreener)
        frame = pd.DataFrame({'거래량': [10], '종가': [100]}, index=['005930'])
        with patch('src.utils.market_calendar.last_business_day', return_value='20260908'), \
             patch('src.trading.morning_screener.stock.get_market_ohlcv_by_ticker', return_value=frame) as fetch:
            self.assertEqual(screener._get_pykrx_value_rank(), ['005930'])
        fetch.assert_called_once_with('20260908', market='KOSPI')

    def test_legacy_mixed_cache_is_not_loaded(self):
        with patch('src.trading.morning_screener.StrategyManager'), \
             patch('src.trading.morning_screener.OllamaSentimentClient'), \
             patch('src.trading.morning_screener.audit'), \
             patch('src.trading.morning_screener.digest'):
            screener = MorningScreener()
        self.assertTrue(screener.cache_path.endswith('pre_analysis_cache_kospi.json'))
        self.assertEqual(len(screener.FALLBACK_CODES), 20)
        self.assertNotIn('247540', screener.FALLBACK_CODES)


if __name__ == '__main__':
    unittest.main()
