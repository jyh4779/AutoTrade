"""Durable, conservative order state and idempotent cumulative-fill accounting."""
import math
import sqlite3
from datetime import datetime
from uuid import uuid4
from contextlib import contextmanager
from src.core.observability.events import audit, now_kst
from src.markets.stocks.risk_policy import policy

ACTIVE = ('SUBMITTING', 'UNKNOWN', 'ACK', 'PARTIAL')


class OrderManager:
    def __init__(self, db_path, domestic, events=None):
        self.db_path, self.domestic = str(db_path), domestic
        self.events = events or audit()
        with self.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS managed_orders(
                    intent_id TEXT PRIMARY KEY, day TEXT, symbol TEXT, side TEXT,
                    name TEXT, requested_qty INTEGER, state TEXT, broker_order_id TEXT,
                    filled_qty INTEGER DEFAULT 0, filled_total REAL DEFAULT 0,
                    cost_basis REAL, score REAL, created_at TEXT, updated_at TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_symbol ON managed_orders(symbol)
                  WHERE state IN ('SUBMITTING','UNKNOWN','ACK','PARTIAL');
                CREATE TABLE IF NOT EXISTS managed_fills(
                    intent_id TEXT, cumulative_qty INTEGER, qty INTEGER, total REAL,
                    trade_log_id INTEGER, PRIMARY KEY(intent_id,cumulative_qty));
                CREATE TABLE IF NOT EXISTS risk_days(day TEXT PRIMARY KEY, basis_cash REAL, created_at TEXT);
                CREATE TABLE IF NOT EXISTS entry_blocks(day TEXT PRIMARY KEY, reason TEXT, created_at TEXT);
            ''')
            columns={r[1] for r in c.execute('PRAGMA table_info(managed_orders)')}
            if 'cancel_requested' not in columns:
                c.execute('ALTER TABLE managed_orders ADD COLUMN cancel_requested INTEGER DEFAULT 0')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def pending(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM managed_orders WHERE state IN ('SUBMITTING','UNKNOWN','ACK','PARTIAL')")]

    def submit(self, symbol, name, qty, side, score=0., cost_basis=0., intent_id=None, risk_context=None):
        if self.events.mode == 'shadow':
            raise ValueError('shadow_mode_cannot_submit_orders')
        if side not in ('BUY','SELL') or not isinstance(qty,int) or qty <= 0:
            raise ValueError('invalid_order')
        day = now_kst().date().isoformat()
        # Daily BUY id survives restarts and prevents accidental same-day re-entry.
        intent_id = intent_id or (f'{day}:BUY:{symbol}' if side == 'BUY' else str(uuid4()))
        ts = now_kst().isoformat()
        self.events.emit('ORDER_INTENT', required=side=='BUY', intent_id=intent_id, symbol=symbol, side=side, qty=qty)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT * FROM managed_orders WHERE intent_id=?', (intent_id,)).fetchone()
            if existing:
                return dict(existing)
            if side == 'BUY' and c.execute("SELECT 1 FROM managed_orders WHERE state IN ('SUBMITTING','UNKNOWN','ACK','PARTIAL') LIMIT 1").fetchone():
                raise ValueError('unresolved_order_blocks_entry')
            if side == 'BUY' and self.events.mode == 'live' and risk_context is None:
                raise ValueError('live_order_requires_risk_context')
            if side == 'BUY' and risk_context is not None:
                limits=policy();cash=risk_context['cash'];price=risk_context['price']
                if cash<=0 or price<=0 or not all(math.isfinite(x) for x in (cash,price)):
                    raise ValueError('invalid_risk_context')
                c.execute('INSERT OR IGNORE INTO risk_days VALUES(?,?,?)',(day,cash,ts))
                basis=c.execute('SELECT basis_cash FROM risk_days WHERE day=?',(day,)).fetchone()[0]
                count=c.execute("SELECT COUNT(*) FROM managed_orders WHERE day=? AND side='BUY' AND state!='REJECTED'",(day,)).fetchone()[0]
                spent=c.execute("SELECT COALESCE(SUM(filled_total),0) FROM managed_orders WHERE day=? AND side='BUY'",(day,)).fetchone()[0]
                pnl=c.execute("SELECT COALESCE(SUM(profit),0),COUNT(*)-COUNT(profit) FROM trade_log WHERE date LIKE ? AND type='SELL'",(day+'%',)).fetchone()
                if (c.execute('SELECT 1 FROM entry_blocks WHERE day=?',(day,)).fetchone()
                        or qty*price>basis*limits['max_position_ratio'] or qty*price>cash-limits['minimum_cash']
                        or spent+qty*price>basis*limits['max_gross_buy_ratio']
                        or count>=risk_context['max_daily_buys'] or pnl[1]>0 or pnl[0]<=-basis*limits['max_daily_loss_pct']):
                    raise ValueError('atomic_risk_limit')
                self.events.emit('ATOMIC_RISK_CHECK',required=True,intent_id=intent_id,cash=cash,basis_cash=basis,
                                 price=price,qty=qty,count=count,spent=spent,realized_profit=pnl[0],
                                 max_daily_buys=risk_context['max_daily_buys'],policy=limits)
            c.execute('INSERT INTO managed_orders(intent_id,day,symbol,side,name,requested_qty,state,cost_basis,score,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (intent_id,day,symbol,side,name,qty,'SUBMITTING',cost_basis,score,ts,ts))
        # SUBMITTING must be durable before the external side effect. Never retry it blindly.
        try:
            result = self.domestic.order_market_price(symbol,qty,is_buy=side=='BUY')
        except Exception:
            result = {'ambiguous': True}
        oid = result.get('output',{}).get('ODNO') or result.get('output',{}).get('odno')
        state = 'ACK' if result.get('rt_cd')=='0' and oid else 'UNKNOWN'
        if result.get('rt_cd') not in (None,'0','9') and not result.get('ambiguous'):
            state='REJECTED'
        with self.connect() as c:
            c.execute('UPDATE managed_orders SET state=?,broker_order_id=?,updated_at=? WHERE intent_id=?',
                      (state,oid,now_kst().isoformat(),intent_id))
        self.events.emit('ORDER_ACK' if state=='ACK' else 'ORDER_'+state,
                         intent_id=intent_id, symbol=symbol, side=side, broker_order_id=oid, state=state)
        return self.get(intent_id)

    def get(self, intent_id):
        with self.connect() as c:
            return dict(c.execute('SELECT * FROM managed_orders WHERE intent_id=?',(intent_id,)).fetchone())

    def apply_detail(self, intent_id, detail):
        qty, total = int(detail.get('qty',0)), float(detail.get('total_amt',0))
        if qty < 0 or total < 0 or not math.isfinite(total):
            raise ValueError('invalid_fill')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            r = dict(c.execute('SELECT * FROM managed_orders WHERE intent_id=?',(intent_id,)).fetchone())
            if qty < r['filled_qty']:
                return r  # delayed older cumulative response
            if qty > r['requested_qty'] or (qty==r['filled_qty'] and abs(total-r['filled_total'])>.01):
                raise ValueError('inconsistent_fill')
            dq, dt = qty-r['filled_qty'], total-r['filled_total']
            if dq:
                if dt <= 0:
                    raise ValueError('invalid_fill_delta')
                price = dt/dq
                basis = r['cost_basis']*dq
                # Preserve the current configured fee assumption, with cumulative rounding.
                fee_rate=policy()['sell_cost_rate']
                tax = math.floor(total*fee_rate)-math.floor(r['filled_total']*fee_rate) if r['side']=='SELL' else 0
                profit = (dt-basis-tax if basis>0 else None) if r['side']=='SELL' else 0
                ret = profit/basis*100 if profit is not None and basis>0 else (0 if r['side']=='BUY' else None)
                cur = c.execute('INSERT INTO trade_log(date,type,code,name,qty,price,total,profit,return_pct,score) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (r['day']+' '+now_kst().strftime('%H:%M:%S'),r['side'],r['symbol'],r['name'],dq,price,dt,profit,ret,r['score']))
                c.execute('INSERT INTO managed_fills VALUES(?,?,?,?,?)',(intent_id,qty,dq,dt,cur.lastrowid))
            state = 'FILLED' if qty==r['requested_qty'] else ('CANCELLED' if detail.get('cancelled') else ('PARTIAL' if qty else 'ACK'))
            c.execute('UPDATE managed_orders SET state=?,filled_qty=?,filled_total=?,updated_at=? WHERE intent_id=?',
                      (state,qty,total,now_kst().isoformat(),intent_id))
        self.events.emit('FILL_RECONCILED', intent_id=intent_id, symbol=r['symbol'], cumulative_qty=qty,
                         cumulative_total=total, delta_qty=dq, state=state, cost_basis_known=r['cost_basis']>0)
        return self.get(intent_id)

    def check_account_loss(self, unrealized_profit):
        day=now_kst().date().isoformat()
        with self.connect() as c:
            row=c.execute('SELECT basis_cash FROM risk_days WHERE day=?',(day,)).fetchone()
            if not row:
                self.events.emit('ACCOUNT_RISK',status='UNKNOWN',reason='daily_basis_not_observed')
                return False
            pnl=c.execute("SELECT COALESCE(SUM(profit),0) FROM trade_log WHERE date LIKE ? AND type='SELL'",(day+'%',)).fetchone()[0]
            breached=pnl+unrealized_profit<=-row[0]*policy()['max_daily_loss_pct']
            if breached:
                c.execute('INSERT OR IGNORE INTO entry_blocks VALUES(?,?,?)',(day,'DAILY_LOSS_LIMIT',now_kst().isoformat()))
        self.events.emit('ACCOUNT_RISK',status='FAIL' if breached else 'PASS',basis_cash=row[0],
                         realized=pnl,unrealized=unrealized_profit,limit_pct=policy()['max_daily_loss_pct'])
        return breached

    def reconcile(self):
        for r in self.pending():
            if not r['broker_order_id']:
                self.events.emit('ORDER_UNKNOWN', intent_id=r['intent_id'], reason='missing_broker_id_requires_review')
                continue
            try:
                detail = self.domestic.get_execution_detail(r['broker_order_id'],r['symbol'],r['side']=='BUY',date=r['day'].replace('-',''))
                if detail is not None:
                    self.apply_detail(r['intent_id'],detail)
                else:
                    self.events.emit('ORDER_UNKNOWN', intent_id=r['intent_id'], reason='broker_query_unavailable')
            except Exception:
                self.events.emit('ORDER_UNKNOWN', intent_id=r['intent_id'], reason='reconciliation_failed')
        return self.pending()

    def cancel_pending(self, intent_id):
        r=self.get(intent_id)
        if self.events.mode=='shadow' or r['state'] not in ACTIVE or not r['broker_order_id'] or r['cancel_requested']:
            return False
        preview=self.domestic.get_cancelable_order(r['broker_order_id'],r['symbol'])
        if not preview or preview['qty']<=0:
            self.events.emit('CANCEL_UNKNOWN',intent_id=intent_id,reason='preflight_unavailable')
            return False
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT state,cancel_requested FROM managed_orders WHERE intent_id=?',(intent_id,)).fetchone()
            if current['state'] not in ACTIVE or current['cancel_requested']:
                return False
            c.execute('UPDATE managed_orders SET cancel_requested=1 WHERE intent_id=?',(intent_id,))
        self.events.emit('CANCEL_REQUESTED',intent_id=intent_id,qty=preview['qty'])
        try:
            result=self.domestic.cancel_order(preview)
        except Exception:
            result={'ambiguous':True}
        # Receipt of a cancellation is not proof that the original order is closed.
        self.events.emit('CANCEL_ACK' if result.get('rt_cd')=='0' else 'CANCEL_UNKNOWN',intent_id=intent_id)
        self.reconcile()
        return self.get(intent_id)['state'] in ('FILLED','CANCELLED')
