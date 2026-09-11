import ast
import importlib
import unittest
from decimal import Decimal
from pathlib import Path
from src.core.models.contracts import Instrument, OrderIntent


class Architecture(unittest.TestCase):
    def test_compatibility_modules_share_state(self):
        pairs = [('src.observability.events','src.core.observability.events'),
                 ('src.trading.kis_auth','src.adapters.kis.kis_auth'),
                 ('src.trading.strategy_logic','src.markets.stocks.strategy'),
                 ('src.trading.auto_trade_main','src.runners.stock_trading')]
        for old,new in pairs:
            self.assertIs(importlib.import_module(old), importlib.import_module(new))

    def test_core_has_no_market_or_adapter_imports(self):
        for p in Path('src/core').rglob('*.py'):
            for node in ast.walk(ast.parse(p.read_text(encoding='utf8'))):
                modules = [node.module or ''] if isinstance(node, ast.ImportFrom) else (
                    [a.name for a in node.names] if isinstance(node,ast.Import) else [])
                for module in modules:
                    self.assertFalse(module.startswith(('src.markets','src.adapters','src.runners','src.trading')), str(p))

    def test_precision_and_identity(self):
        stock = Instrument('stocks','KRX','A','A','KRW',Decimal('1'),Decimal('1'),Decimal('1'))
        coin = Instrument('crypto','exchange','A','A','KRW',Decimal('.0001'),Decimal('1'),Decimal('5000'))
        a = OrderIntent(stock,'account','strategy','signal','BUY',quantity=Decimal('1'))
        b = OrderIntent(coin,'account','strategy','signal','BUY',quantity=Decimal('.0001'))
        self.assertNotEqual(a.identity,b.identity)
        with self.assertRaises(ValueError):
            OrderIntent(stock,'account','strategy','signal','BUY',quantity=Decimal('.5'))
        with self.assertRaises(ValueError):
            OrderIntent(coin,'account','strategy','signal','BUY',amount=Decimal('4999'))
