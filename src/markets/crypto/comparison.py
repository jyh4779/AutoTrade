"""Independent paper lanes with immutable assumptions and shared observation IDs.

A sampled IOC approximation, not a reconstruction of exchange queue priority.
"""
import json,sqlite3,hashlib
from pathlib import Path
from decimal import Decimal as D
from dataclasses import asdict
from contextlib import contextmanager
from .execution_profile import ExecutionProfile

BASE='upbit_krw_momentum_v1'
EXPERIMENT='relative_entry_v1'

class Comparison:
    def __init__(self,path,profile=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        config=self.path.parent/'comparison_profile.json'
        if profile is None and config.exists():profile=ExecutionProfile(**json.loads(config.read_text(encoding='utf8'))).validate()
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS profile(id TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY,strategy TEXT,symbol TEXT,at REAL,eligible INTEGER,reason TEXT);
            CREATE TABLE IF NOT EXISTS consumed(id TEXT PRIMARY KEY,reason TEXT);
            CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,strategy TEXT,symbol TEXT,at REAL,qty TEXT,cost TEXT,fee TEXT);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,signal_id TEXT,strategy TEXT,symbol TEXT,side TEXT,at REAL,amount TEXT,state TEXT,reason TEXT);
            CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY,order_id TEXT,observation_id TEXT,at REAL,qty TEXT,value TEXT,fee TEXT,partial INTEGER);
            CREATE TABLE IF NOT EXISTS closed(id TEXT PRIMARY KEY,strategy TEXT,symbol TEXT,at REAL,profit TEXT,reason TEXT);
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,at REAL,symbol TEXT,book_timestamp REAL);
            ''')
            existing=c.execute('select * from profile').fetchone()
            if existing:
                self.profile=ExecutionProfile(**json.loads(existing['payload'])).validate()
                if profile and self.profile.identity()!=profile.identity():raise ValueError('PROFILE_CHANGE_REQUIRES_NEW_LEDGER')
            else:
                self.profile=(profile or ExecutionProfile()).validate()
                c.execute('insert into profile values(?,?)',(self.profile.identity(),json.dumps(asdict(self.profile))))

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def signal(self,identity,strategy,symbol,at,eligible,reason):
        if strategy not in (BASE,EXPERIMENT):raise ValueError('UNKNOWN_STRATEGY')
        with self.connect() as c:
            c.execute('insert or ignore into signals values(?,?,?,?,?,?)',(identity,strategy,symbol,at,int(eligible),reason))

    def watch_symbols(self):
        with self.connect() as c:
            return {r[0] for r in c.execute('select symbol from positions union select symbol from orders where state="PENDING" union select symbol from signals where id not in (select id from consumed)')}

    @staticmethod
    def fill(book,side,amount):
        qty=value=D(0);remaining=amount
        for u in book['orderbook_units']:
            price=D(str(u['ask_price' if side=='BUY' else 'bid_price']))
            size=D(str(u['ask_size' if side=='BUY' else 'bid_size']))
            if not price.is_finite() or not size.is_finite() or price<=0 or size<0:raise ValueError('INVALID_BOOK')
            take=min(size,remaining/price) if side=='BUY' else min(size,remaining)
            qty+=take;value+=take*price;remaining-=take*price if side=='BUY' else take
            if remaining<=D('.00000001'):break
        return qty,value,remaining>D('.00000001')

    def observe(self,symbol,book,at,allowed):
        if book['market']!=symbol or not -5<=at-book['timestamp']/1000<=30:raise ValueError('STALE_BOOK')
        oid=hashlib.sha256(json.dumps([symbol,at,book],sort_keys=True).encode()).hexdigest()
        cfg=self.profile; events=[]
        with self.connect() as c:
            if c.execute('select 1 from observations where id=?',(oid,)).fetchone():return []
            c.execute('insert into observations values(?,?,?,?)',(oid,at,symbol,book['timestamp']))
            # Fill only intents created before this observation and after configured latency.
            for o in c.execute('select * from orders where symbol=? and state="PENDING"',(symbol,)).fetchall():
                if at-o['at']<cfg.latency_seconds or at<=o['at']:continue
                if o['side']=='BUY' and (not allowed or at-o['at']>1200):
                    c.execute('update orders set state="CANCELLED" where id=?',(o['id'],));continue
                qty,value,partial=self.fill(book,o['side'],D(o['amount']))
                if o['side']=='BUY':
                    ask=D(str(book['orderbook_units'][0]['ask_price']));bid=D(str(book['orderbook_units'][0]['bid_price']))
                    if ask<bid or (ask-bid)/((ask+bid)/2)>D('.002') or (qty and value/qty/ask-1>D('.002')):
                        c.execute('update orders set state="CANCELLED" where id=?',(o['id'],));continue
                c.execute('update orders set state=? where id=?',('PARTIAL_CANCELLED' if partial else 'FILLED',o['id']))
                if not qty:continue
                fee=value*D(cfg.buy_fee if o['side']=='BUY' else cfg.sell_fee)
                c.execute('insert into fills values(?,?,?,?,?,?,?,?)',(o['id'],o['id'],oid,at,str(qty),str(value),str(fee),int(partial)))
                if o['side']=='BUY':
                    c.execute('insert into positions values(?,?,?,?,?,?,?)',(o['signal_id'],o['strategy'],symbol,at,str(qty),str(value),str(fee)))
                else:
                    p=c.execute('select * from positions where id=?',(o['signal_id'],)).fetchone()
                    fraction=qty/D(p['qty']);cost=D(p['cost'])*fraction;entry_fee=D(p['fee'])*fraction
                    profit=value-fee-cost-entry_fee
                    c.execute('insert into closed values(?,?,?,?,?,?)',(o['id'],o['strategy'],symbol,at,str(profit),o['reason']))
                    remaining=D(p['qty'])-qty
                    if remaining<=D('.00000001'):c.execute('delete from positions where id=?',(p['id'],))
                    else:c.execute('update positions set qty=?,cost=?,fee=? where id=?',(str(remaining),str(D(p['cost'])-cost),str(D(p['fee'])-entry_fee),p['id']))
                events.append(dict(order_id=o['id'],strategy=o['strategy'],side=o['side'],observation_id=oid,partial=partial))
            for p in c.execute('select * from positions where symbol=?',(symbol,)).fetchall():
                if c.execute('select 1 from orders where signal_id=? and state="PENDING"',(p['id'],)).fetchone():continue
                qty,value,_=self.fill(book,'SELL',D(p['qty']))
                if not qty:continue
                change=(value/qty)/(D(p['cost'])/D(p['qty']))-1
                reason='STOP' if change<=D('-.03') else 'TARGET' if change>=D('.05') else ('TIME' if at-p['at']>=3600 else None)
                if reason and value>=D(cfg.minimum_order):
                    identity=hashlib.sha256(f"{p['id']}:SELL:{at}".encode()).hexdigest()
                    c.execute('insert into orders values(?,?,?,?,?,?,?,?,?)',(identity,p['id'],p['strategy'],symbol,'SELL',at,p['qty'],'PENDING',reason))
            for s in c.execute('select * from signals where symbol=? and id not in (select id from consumed)',(symbol,)).fetchall():
                if at<=s['at']:continue
                reason='QUEUED'
                if at-s['at']>1200:reason='EXPIRED'
                elif not allowed or not s['eligible']:reason='BLOCKED'
                holdings=c.execute('select * from positions where strategy=?',(s['strategy'],)).fetchall()
                pending=c.execute('select * from orders where strategy=? and side="BUY" and state="PENDING"',(s['strategy'],)).fetchall()
                realized=sum((D(r[0]) for r in c.execute('select profit from closed where strategy=?',(s['strategy'],))),D(0))
                cash=D(cfg.initial_cash)+realized-sum((D(p['cost'])+D(p['fee']) for p in holdings),D(0))-sum((D(o['amount'])*(1+D(cfg.buy_fee)) for o in pending),D(0))
                if len(holdings)+len(pending)>=cfg.max_positions or any(p['symbol']==symbol for p in holdings+pending):reason='POSITION_LIMIT'
                if cash<D(cfg.order_krw)*(1+D(cfg.buy_fee)):reason='CASH_LIMIT'
                c.execute('insert into consumed values(?,?)',(s['id'],reason))
                if reason=='QUEUED':
                    c.execute('insert into orders values(?,?,?,?,?,?,?,?,?)',(s['id'],s['id'],s['strategy'],symbol,'BUY',at,cfg.order_krw,'PENDING','ENTRY'))
        return events

    def report(self):
        with self.connect() as c:
            lanes={}
            for strategy in (BASE,EXPERIMENT):
                profits=[D(r[0]) for r in c.execute('select profit from closed where strategy=?',(strategy,))]
                lanes[strategy]=dict(mode='paper',realized_profit=str(sum(profits,D(0))),exit_fills=len(profits),
                    open_positions=c.execute('select count(*) from positions where strategy=?',(strategy,)).fetchone()[0],
                    pending_orders=c.execute('select count(*) from orders where strategy=? and state="PENDING"',(strategy,)).fetchone()[0])
            return dict(profile=asdict(self.profile),profile_id=self.profile.identity(),lanes=lanes,
                live=dict(status='DISABLED',reason='ACCOUNT_AND_LIMITS_NOT_CONFIGURED'),
                fill_model='later_sampled_orderbook_partial_IOC',queue_priority_verified=False)
