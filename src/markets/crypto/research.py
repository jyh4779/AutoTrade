"""Persistent shadow feedback. Orders are simulated only at later observed books."""
import json
import statistics
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

D=Decimal
FEE=D('.0005')  # Research assumption per side, not a verified account fee.
BUDGET=D('100000')
INITIAL=D('1000000')
MAX_POSITIONS=3
HOLD_SECONDS=3600


class Research:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS observations(at REAL,symbol TEXT,turnover REAL,
                PRIMARY KEY(at,symbol));
            CREATE TABLE IF NOT EXISTS membership(symbol TEXT PRIMARY KEY,at REAL);
            CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY,strategy TEXT,symbol TEXT,
                at REAL,score REAL,eligible INTEGER,reason TEXT);
            CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,strategy TEXT,symbol TEXT,
                entry_at REAL,price TEXT,qty TEXT,cost TEXT,fee TEXT);
            CREATE TABLE IF NOT EXISTS closed(id TEXT PRIMARY KEY,strategy TEXT,symbol TEXT,
                entry_at REAL,exit_at REAL,profit TEXT,return_pct REAL,reason TEXT);
            CREATE TABLE IF NOT EXISTS consumed(id TEXT PRIMARY KEY,reason TEXT);
            CREATE TABLE IF NOT EXISTS books(at REAL,symbol TEXT,payload TEXT,PRIMARY KEY(at,symbol));
            CREATE TABLE IF NOT EXISTS references_(id TEXT PRIMARY KEY,price TEXT);
            CREATE TABLE IF NOT EXISTS outcomes(id TEXT PRIMARY KEY,at REAL,return_pct REAL);
            ''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def observe_universe(self,tickers,at):
        with self.connect() as c:
            c.executemany('INSERT OR IGNORE INTO observations VALUES(?,?,?)',
                [(at,q['market'],float(q['acc_trade_price_24h'])) for q in tickers])
            return {r['symbol'] for r in c.execute('SELECT symbol FROM membership WHERE at>?',(at-3600,))}

    def remember(self,symbols,at):
        with self.connect() as c:
            c.execute('DELETE FROM membership')
            c.executemany('INSERT INTO membership VALUES(?,?)',[(s,at) for s in symbols])

    def liquidity_history(self,symbol,at):
        with self.connect() as c:
            rows=c.execute('SELECT at,turnover FROM observations WHERE symbol=? AND at<? AND at>=? ORDER BY at',
                           (symbol,at,at-7*86400)).fetchall()
        days={int(r['at']//86400):r['turnover'] for r in rows if int(r['at']//86400)<int(at//86400)}
        return dict(observed_days=len(days),median_turnover=statistics.median(days.values()) if len(days)>=3 else None,
                    status='PASS' if len(days)>=3 else 'UNKNOWN_INSUFFICIENT_DAYS')

    def pending_symbols(self):
        with self.connect() as c:
            return {r[0] for r in c.execute('SELECT symbol FROM positions')}

    def watch_symbols(self,at):
        with self.connect() as c:
            symbols={r[0] for r in c.execute('SELECT symbol FROM positions')}
            symbols.update(r[0] for r in c.execute('SELECT DISTINCT symbol FROM signals WHERE at>=?',(at-4500,)))
            return symbols

    @staticmethod
    def fill(book,side,amount):
        remaining=amount;value=D(0);quantity=D(0)
        for u in book['orderbook_units']:
            price=D(str(u['ask_price' if side=='BUY' else 'bid_price']))
            size=D(str(u['ask_size' if side=='BUY' else 'bid_size']))
            if not price.is_finite() or not size.is_finite() or price<=0 or size<0:raise ValueError('INVALID_BOOK')
            take=min(size,remaining/price) if side=='BUY' else min(size,remaining)
            quantity+=take;value+=take*price
            remaining-=take*price if side=='BUY' else take
            if remaining<=D('0.00000001'):return quantity,value
        raise ValueError('INSUFFICIENT_BOOK_DEPTH')

    def advance(self,symbol,book,at,market_allowed):
        """No backdated fill: signal < observation <= signal+20min. No intrabar claims."""
        if book['market']!=symbol or not -5<=at-float(book['timestamp'])/1000<=30:
            raise ValueError('STALE_OR_MISMATCHED_BOOK')
        actions=[]
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO books VALUES(?,?,?)',(at,symbol,json.dumps(book)))
            for s in c.execute('SELECT s.id,s.at,r.price FROM signals s JOIN references_ r ON s.id=r.id WHERE s.symbol=? AND s.at<=? AND s.id NOT IN (SELECT id FROM outcomes)',(symbol,at-HOLD_SECONDS)).fetchall():
                # Strict evaluation window; late observations are never labelled as 1h returns.
                if at-s['at']>HOLD_SECONDS+900:continue
                bid=D(str(book['orderbook_units'][0]['bid_price']))
                change=(bid*(1-FEE)-D(s['price'])*(1+FEE))/D(s['price'])
                c.execute('INSERT INTO outcomes VALUES(?,?,?)',(s['id'],at,float(change)))
            for p in c.execute('SELECT * FROM positions WHERE symbol=?',(symbol,)).fetchall():
                qty,value=self.fill(book,'SELL',D(p['qty']))
                change=value/D(p['cost'])-1
                reason='STOP' if change<=D('-.03') else 'TARGET' if change>=D('.05') else (
                    'TIME' if at-p['entry_at']>=HOLD_SECONDS else None)
                if not reason:continue
                net=value*(1-FEE)-D(p['cost'])-D(p['fee'])
                c.execute('INSERT INTO closed VALUES(?,?,?,?,?,?,?,?)',
                    (p['id'],p['strategy'],symbol,p['entry_at'],at,str(net),float(net/D(p['cost'])),reason))
                c.execute('DELETE FROM positions WHERE id=?',(p['id'],));actions.append(dict(id=p['id'],action='EXIT',reason=reason))
            signals=c.execute('SELECT * FROM signals WHERE symbol=? AND at<? AND id NOT IN (SELECT id FROM consumed) ORDER BY at,score DESC',(symbol,at)).fetchall()
            for s in signals:
                reason=None
                if at-s['at']>1200:reason='SIGNAL_EXPIRED'
                elif not s['eligible'] or not market_allowed:reason='ENTRY_BLOCKED'
                top=book['orderbook_units'][0]
                ask=D(str(top['ask_price']));bid=D(str(top['bid_price']))
                if bid<=0 or ask<bid or (ask-bid)/((ask+bid)/2)>D('.002'):
                    reason=reason or 'SPREAD_LIMIT'
                holdings=c.execute('SELECT * FROM positions WHERE strategy=?',(s['strategy'],)).fetchall()
                profits=sum((D(r[0]) for r in c.execute('SELECT profit FROM closed WHERE strategy=?',(s['strategy'],))),D(0))
                available=INITIAL+profits-sum((D(p['cost'])+D(p['fee']) for p in holdings),D(0))
                if len(holdings)>=MAX_POSITIONS or any(p['symbol']==symbol for p in holdings):reason=reason or 'POSITION_LIMIT'
                if available<BUDGET*(1+FEE):reason=reason or 'CASH_LIMIT'
                if not reason:
                    qty,value=self.fill(book,'BUY',BUDGET)
                    if (value/qty)/ask-1>D('.002'):
                        c.execute('INSERT INTO consumed VALUES(?,?)',(s['id'],'SLIPPAGE_LIMIT'))
                        actions.append(dict(id=s['id'],action='SLIPPAGE_LIMIT'))
                        continue
                    c.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?)',
                        (s['id'],s['strategy'],symbol,at,str(value/qty),str(qty),str(value),str(value*FEE)))
                    reason='OPENED'
                c.execute('INSERT INTO consumed VALUES(?,?)',(s['id'],reason))
                actions.append(dict(id=s['id'],action=reason))
        return actions

    def signal(self,identity,strategy,symbol,at,score,eligible,reason,reference=None):
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,?)',
                      (identity,strategy,symbol,at,score,int(eligible),reason))
            if reference is not None:
                c.execute('INSERT OR IGNORE INTO references_ VALUES(?,?)',(identity,str(reference)))

    def feedback(self):
        with self.connect() as c:
            strategies=[r[0] for r in c.execute('SELECT DISTINCT strategy FROM signals')]
            result={}
            for strategy in strategies:
                rows=c.execute('SELECT * FROM closed WHERE strategy=?',(strategy,)).fetchall()
                result[strategy]=dict(signals=c.execute('SELECT count(*) FROM signals WHERE strategy=?',(strategy,)).fetchone()[0],
                    closed=len(rows),open=c.execute('SELECT count(*) FROM positions WHERE strategy=?',(strategy,)).fetchone()[0],
                    realized_profit=str(sum((D(r['profit']) for r in rows),D(0))),
                    win_rate=sum(D(r['profit'])>0 for r in rows)/len(rows) if rows else None)
                samples=c.execute('SELECT s.score,s.eligible,s.reason,o.return_pct FROM signals s JOIN outcomes o ON s.id=o.id WHERE s.strategy=?',(strategy,)).fetchall()
                buckets={}
                for sample in samples:
                    key=str(min(9,int(sample['score']*10)))
                    buckets.setdefault(key,[]).append(sample['return_pct'])
                result[strategy]['score_decile_outcomes']={k:dict(count=len(v),mean_return=sum(v)/len(v)) for k,v in buckets.items()}
                result[strategy]['labelled_signals']=len(samples)
                result[strategy]['unlabelled_signals']=result[strategy]['signals']-len(samples)
                result[strategy]['outcome_method']='signal_ask_to_bid_observed_60_to_75_minutes_later_fee_adjusted'
            return dict(strategies=result,fee_assumption=str(FEE),method='later_observed_orderbook',
                intrabar_path_verified=False,performance_validation='NOT_ESTABLISHED',
                automatic_weight_changes=False)
