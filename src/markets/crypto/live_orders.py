"""Durable live order boundary. No paper strategy can call this via the daemon.
Uncertain submissions remain unresolved until queried by the same identifier.
"""
import sqlite3,json,time,hashlib
from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal as D
from .comparison import BASE

class LiveOrders:
    def __init__(self,path,api,enabled=False,max_order_krw=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.api=api;self.enabled=enabled;self.max_order=D(str(max_order_krw or 0))
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS orders(identifier TEXT PRIMARY KEY,signal_id TEXT,strategy TEXT,side TEXT,payload TEXT,state TEXT,response TEXT);
            CREATE TABLE IF NOT EXISTS observations(identifier TEXT,at REAL,payload TEXT);
            ''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30)
        try:
            with c:yield c
        finally:c.close()

    def submit(self,signal_id,strategy,symbol,side,amount):
        if not self.enabled:raise ValueError('LIVE_DISABLED')
        if strategy!=BASE:raise ValueError('LIVE_STRATEGY_FORBIDDEN')
        if not symbol.startswith('KRW-') or not symbol[4:].isalnum():raise ValueError('KRW_ONLY')
        value=D(str(amount))
        if not value.is_finite() or value<=0:raise ValueError('INVALID_ORDER')
        if side not in ('BUY','SELL'):raise ValueError('INVALID_SIDE')
        if side=='BUY' and (self.max_order<=0 or value>self.max_order):raise ValueError('ORDER_LIMIT')
        identifier=hashlib.sha256(f'upbit:live:{strategy}:{signal_id}:{side}'.encode()).hexdigest()
        payload=dict(identifier=identifier,market=symbol,side='bid' if side=='BUY' else 'ask',ord_type='price' if side=='BUY' else 'market')
        payload['price' if side=='BUY' else 'volume']=str(value)
        with self.connect() as c:
            if c.execute('select 1 from orders where identifier=?',(identifier,)).fetchone():return identifier
            if c.execute('select 1 from orders where state not in ("done","cancel")').fetchone():raise ValueError('UNRESOLVED_ORDER')
            c.execute('insert into orders values(?,?,?,?,?,?,?)',(identifier,signal_id,strategy,side,json.dumps(payload),'SUBMITTING',None))
        try:response=self.api.submit(payload)
        except Exception:
            with self.connect() as c:c.execute('update orders set state="UNKNOWN" where identifier=?',(identifier,))
            raise
        self._record(identifier,response)
        return identifier

    def _record(self,identifier,response):
        # Preserve cumulative execution amounts for reconciliation; no fabricated fills.
        if response.get('identifier')!=identifier:raise ValueError('ORDER_ID_MISMATCH')
        safe={k:response[k] for k in ('identifier','uuid','state','side','market','executed_volume','remaining_volume','paid_fee','trades') if k in response}
        state=safe.get('state','UNKNOWN')
        if state not in ('wait','watch','done','cancel'):state='UNKNOWN'
        with self.connect() as c:
            c.execute('update orders set state=?,response=? where identifier=?',(state,json.dumps(safe),identifier))
            c.execute('insert into observations values(?,?,?)',(identifier,time.time(),json.dumps(safe)))

    def reconcile(self):
        with self.connect() as c:ids=[r[0] for r in c.execute('select identifier from orders where state not in ("done","cancel")')]
        for identity in ids:self._record(identity,self.api.order(identity))
        return len(ids)
