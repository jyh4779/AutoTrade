
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.adapters.kis.kis_domestic import KISDomestic
from src.adapters.kis.kis_account import KISAccount
import sqlite3
import pandas as pd
from datetime import datetime
from src.core.observability.events import audit, now_kst
from src.markets.stocks.order_manager import OrderManager
import time

# 수수료율 상수 (한국투자증권 비대면 기준 — 매매 수수료 무료 이벤트 적용)
# 실제 비용 = 거래세 0.18% + 유관기관 제비용 ~0.018% = 약 0.198% (매도 시에만 부과)
BUY_FEE_RATE = 0.0           # 매수 수수료 0% (비대면 무료)
SELL_FEE_RATE = 0.0           # 매도 수수료 0% (비대면 무료)
SELL_TAX_RATE = 0.00198       # 거래세+유관기관 제비용 0.198% (매도금액 기준)

class KISTrader:
    def __init__(self, db_path="D:\\ML\\data\\portfolio.db"):
        self.domestic = KISDomestic()
        self.account = KISAccount()
        self.db_path = db_path
        self.events = audit()
        if self.domestic.auth.is_vts and self.events.mode=='live':
            self.events.mode='vts'
        self.events.emit('EXECUTION_CONTEXT',broker_mode='vts' if self.domestic.auth.is_vts else 'real')
        self.orders = OrderManager(db_path, self.domestic, self.events)

    def get_balance(self):
        data = self.account.get_balance()
        if data.get('rt_cd') == '0':
            sum_data = data.get('output2', [{}])[0]
            return float(sum_data.get('dnca_tot_amt', 0))
        return 0.0

    def get_current_price(self, code):
        return self.domestic.get_current_price(code)

    def _wait_and_get_execution(self, order_no, code, is_buy, max_wait=5):
        """주문 후 체결 내역이 반영될 때까지 잠시 대기하고 실제 체결가를 조회합니다."""
        time.sleep(1.5)  # 체결 반영 대기
        for attempt in range(max_wait):
            detail = self.domestic.get_execution_detail(order_no, code, is_buy)
            if detail and detail.get("qty", 0) > 0:
                return detail
            time.sleep(1.0)
        return None

    def buy(self, code, name, quantity, score=0.0):
        # Fresh broker state and unresolved orders are checked again at submission.
        if not self.sync_with_real_account():
            self.events.emit('ENTRY_BLOCKED', symbol=code, reason='account_unavailable')
            return False
        self.orders.reconcile()
        if self.orders.pending():
            self.events.emit('ENTRY_BLOCKED', symbol=code, reason='unresolved_order')
            return False
        from src.markets.stocks.strategy_manager import StrategyManager
        weights = StrategyManager().get_weights()
        quote = self.domestic.get_current_quote(code)
        if not quote:
            self.events.emit('ENTRY_BLOCKED', symbol=code, reason='quote_unavailable')
            return False
        price = quote['price']
        cash = self.get_balance()
        with self.orders.connect() as c:
            buys = c.execute("SELECT COUNT(*) FROM managed_orders WHERE day=? AND side='BUY' AND state!='REJECTED'", (now_kst().date().isoformat(),)).fetchone()[0]
        allowed = (quantity > 0 and quantity*price <= cash*.20 and
                   cash-quantity*price >= 100000 and buys < weights.get('max_daily_buys',3))
        self.events.emit('RISK_CHECKED', required=True, symbol=code, qty=quantity,
                         price=price, cash=cash, ratio=.20, reserve=100000,
                         daily_buys=buys, max_daily_buys=weights.get('max_daily_buys',3), allowed=allowed)
        if not allowed:
            return False
        try:
            order = self.orders.submit(code,name,int(quantity),'BUY',score=score,
                                       risk_context=dict(cash=cash,price=price,max_daily_buys=weights['max_daily_buys']))
            if order['broker_order_id']:
                time.sleep(1.5)
                self.orders.reconcile()
            self.sync_with_real_account()
            return self.orders.get(order['intent_id'])['state'] == 'FILLED'
        except (ValueError, sqlite3.IntegrityError):
            self.events.emit('ENTRY_BLOCKED', symbol=code, reason='order_state_conflict')
            return False

    def sell(self, code, quantity=None, score=0.0):
        if not self.sync_with_real_account():
            self.events.emit('EXIT_PENDING', symbol=code, reason='account_unavailable')
            return False
        self.orders.reconcile()
        for pending in self.orders.pending():
            if pending['symbol']==code and pending['side']=='BUY':
                self.orders.cancel_pending(pending['intent_id'])
        if any(o['symbol']==code for o in self.orders.pending()):
            self.events.emit('EXIT_PENDING',symbol=code,reason='existing_order_not_closed')
            return False
        with self.orders.connect() as c:
            row = c.execute('SELECT qty,name,avg_price FROM holdings WHERE code=?',(code,)).fetchone()
        if not row:
            return False
        qty = min(row[0], quantity) if quantity is not None else row[0]
        try:
            order = self.orders.submit(code,row[1],int(qty),'SELL',score=score,cost_basis=row[2])
            if order['broker_order_id']:
                time.sleep(1.5)
                self.orders.reconcile()
            self.sync_with_real_account()
            return self.orders.get(order['intent_id'])['state'] == 'FILLED'
        except (ValueError, sqlite3.IntegrityError):
            self.events.emit('EXIT_PENDING', symbol=code, reason='order_state_conflict')
            return False

    def _get_buy_score(self, code: str) -> float:
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "SELECT score FROM trade_log WHERE code=? AND type='BUY' ORDER BY date DESC LIMIT 1",
                (code,)
            )
            row = c.fetchone()
            conn.close()
            return row[0] if row else 0.0
        except Exception:
            return 0.0

    def sell_all(self):
        if not self.sync_with_real_account():
            return False
        self.orders.reconcile()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT code FROM holdings")
        codes = [r[0] for r in c.fetchall()]
        conn.close()
        for code in codes:
            self.events.emit('EXIT_TRIGGERED', symbol=code, reason='TIME_OR_ROUTINE')
            self.sell(code, score=self._get_buy_score(code))
        synced = self.sync_with_real_account()
        self.events.emit('LIQUIDATION_CHECK', confirmed=synced, remaining=self.get_holdings() if synced else None,
                         pending_orders=len(self.orders.pending()))
        return synced and not self.get_holdings() and not self.orders.pending()

    def get_holdings(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT code, name, qty, avg_price FROM holdings")
        res = c.fetchall()
        conn.close()
        return res

    def status(self):
        self.sync_with_real_account()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT amount FROM balance WHERE id=1")
        row = c.fetchone()
        balance = row[0] if row else 0.0

        df_holdings = pd.read_sql("SELECT * FROM holdings", conn)
        conn.close()

        print("\n--- [KIS REAL/VTS] Portfolio Status ---")
        print(f"Cash Balance: {balance:,.0f} KRW")

        if not df_holdings.empty:
            print("\nHoldings:")
            for _, row in df_holdings.iterrows():
                curr = self.get_current_price(row['code']) or row['avg_price']
                pnl_p = ((curr - row['avg_price']) / row['avg_price'] * 100) if row['avg_price'] != 0 else 0
                print(f" - {row['name']}: {row['qty']} shares | Avg: {row['avg_price']:,.0f} | Cur: {curr:,.0f} | P&L: {pnl_p:.2f}%")

    def sync_with_real_account(self):
        print("[KIS] Synchronizing DB with Real KIS Account...")
        data = self.account.get_balance()
        if data.get('rt_cd') != '0':
            self.events.emit('ACCOUNT_UNAVAILABLE')
            return False

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Update Balance
        sum_data = data.get('output2', [{}])[0]
        real_cash = float(sum_data.get('dnca_tot_amt', 0))
        c.execute("UPDATE balance SET amount = ?, updated_at = CURRENT_TIMESTAMP WHERE id=1", (real_cash,))

        # Update Holdings (KIS API가 제공하는 실제 종목명 사용)
        c.execute("DELETE FROM holdings")
        output1 = data.get('output1', [])
        for item in output1:
            qty = int(item.get('hldg_qty', 0))
            if qty > 0:
                c.execute("INSERT INTO holdings (code, name, qty, avg_price) VALUES (?, ?, ?, ?)",
                          (item.get('pdno'), item.get('prdt_name'), qty, float(item.get('pchs_avg_pric', 0))))

        conn.commit()
        conn.close()
        with self.orders.connect() as verify:
            observed = [dict(r) for r in verify.execute('SELECT code,qty,avg_price FROM holdings ORDER BY code')]
        self.events.emit('ACCOUNT_RECONCILED', cash=real_cash, holdings=observed,
                         broker_holdings=[dict(code=i.get('pdno'),qty=int(i.get('hldg_qty',0)),avg_price=float(i.get('pchs_avg_pric',0))) for i in output1 if int(i.get('hldg_qty',0))>0])
        print(f"[KIS] Sync Complete. Cash: {real_cash:,.0f}")
        return True

if __name__ == "__main__":
    trader = KISTrader()
    print("KIS Trader Engine Ready.")
