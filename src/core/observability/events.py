import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[3]
KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 1
_local = threading.local()
_default = None


def now_kst():
    return datetime.now(KST)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def release_hash(root=ROOT):
    h = hashlib.sha256()
    for path in sorted((Path(root) / 'src').rglob('*.py')):
        h.update(str(path.relative_to(root)).replace('\\', '/').encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def sanitized(value):
    if isinstance(value, dict):
        return {k: sanitized(v) for k, v in value.items()
                if not any(s in k.lower() for s in ('token', 'secret', 'appkey', 'app_key', 'authorization', 'account_no', 'cano'))}
    if isinstance(value, (tuple, list)):
        return [sanitized(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class EventStore:
    def __init__(self, root=ROOT, mode=None):
        self.root = Path(root)
        self.path = self.root / 'data/audit.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.mode = mode or os.environ.get('ML_EXECUTION_MODE', 'live')
        self.run_id = os.environ.get('ML_RUN_ID') or str(uuid4())
        self.session_id = str(uuid4())
        self.code_version = release_hash(ROOT)
        with self.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE,
                    day TEXT, run_id TEXT, session_id TEXT, kind TEXT, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_day ON events(day,kind);
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')
        self.emit('PROCESS_STARTED', pid=os.getpid(), component=Path(os.sys.argv[0]).name)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.execute('PRAGMA busy_timeout=30000')
        try:
            with c:
                yield c
        finally:
            c.close()

    def snapshot(self, value):
        value = sanitized(value)
        text = canonical(value)
        sid = digest(value)
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?)', (sid, text))
        return sid

    def emit(self, kind, required=False, **fields):
        try:
            ts = now_kst()
            config = {}
            path = self.root / 'data/strategy_config.json'
            if path.exists():
                config = json.loads(path.read_text(encoding='utf-8'))
            event = dict(event_id=str(uuid4()), event_time_utc=ts.astimezone(timezone.utc).isoformat(),
                         trading_date_kst=ts.date().isoformat(), run_id=self.run_id,
                         session_id=self.session_id, schema_version=SCHEMA_VERSION,
                         code_version=self.code_version, execution_mode=self.mode,
                         event_type=kind, config_file_hash=digest(config), **sanitized(fields))
            with self.connect() as c:
                c.execute('INSERT INTO events(event_id,day,run_id,session_id,kind,payload) VALUES (?,?,?,?,?,?)',
                          (event['event_id'], event['trading_date_kst'], self.run_id,
                           self.session_id, kind, canonical(event)))
            return event['event_id']
        except Exception:
            # Do not expose API exceptions or credentials in fallback output.
            print('[AUDIT] event persistence failed: ' + kind, flush=True)
            if required:
                raise
            return None

    def export(self, day):
        with self.connect() as c:
            rows = c.execute('SELECT payload FROM events WHERE day=? ORDER BY seq', (day,)).fetchall()
        out = self.root / 'log/events' / (day + '.jsonl')
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix('.tmp')
        tmp.write_text('\n'.join(r[0] for r in rows) + '\n', encoding='utf-8')
        tmp.replace(out)
        return out


class EmergencyStore:
    """Exit evidence fallback. Never authorizes new risk when the primary store fails."""
    def __init__(self, root):
        self.root = Path(root)
        self.mode = os.environ.get('ML_EXECUTION_MODE', 'live')

    def emit(self, kind, required=False, **fields):
        if required:
            raise RuntimeError('primary_audit_store_unavailable')
        try:
            path=self.root/'log/emergency.jsonl'
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('a',encoding='utf-8') as stream:
                stream.write(canonical(dict(event_type=kind,time=now_kst().isoformat(),**sanitized(fields)))+'\n')
        except Exception:
            print('[AUDIT] primary and fallback persistence unavailable',flush=True)
        return None


def audit():
    global _default
    if _default is None:
        root=Path(os.environ.get('ML_WORKSPACE', ROOT))
        try:
            _default = EventStore(root)
        except Exception:
            _default = EmergencyStore(root)
    return _default
