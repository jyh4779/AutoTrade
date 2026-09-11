"""Process identity and Windows singleton protection; no trading operations."""
import ctypes
import hashlib
import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime
import psutil


class Singleton:
    def __init__(self, root, role):
        self.root = Path(root).resolve()
        scope = (str(self.root).casefold() if os.name=='nt' else str(self.root)) + ':' + role
        self.name = 'Global\\ML_' + hashlib.sha256(scope.encode()).hexdigest()
        self.handle = None
        self.file = None

    def acquire(self):
        if os.name != 'nt':
            import fcntl
            directory=self.root/'locks'
            directory.mkdir(parents=True,exist_ok=True)
            self.file=(directory/(self.name.split('_',1)[1]+'.lock')).open('a+')
            try:
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                self.file.close();self.file=None
                return False
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        handle = self.kernel.CreateMutexW(None, True, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(error, 'singleton unavailable')
        if error == 183:
            self.kernel.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def close(self):
        if self.file is not None:
            import fcntl
            fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            self.file.close();self.file=None
        if self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def watchdogs(root):
    """Discover instrumented watchdogs, including legacy orphans. Never kill by PID alone."""
    path = Path(root)/'data/audit.db'
    if not path.exists():
        return []
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as c:
        starts = [json.loads(r[0]) for r in c.execute(
            "SELECT payload FROM events WHERE kind='PROCESS_STARTED' ORDER BY seq")]
        result = []
        for e in starts:
            if e.get('component') not in ('watchdog.py','stock_watchdog.py'):
                continue
            try:
                p = psutil.Process(e['pid'])
                created = p.create_time()
                logged = datetime.fromisoformat(e['event_time_utc']).timestamp()
                if p.name().lower() != 'python.exe' or not 0 <= logged-created <= 120:
                    continue
                row = c.execute('SELECT payload FROM events WHERE session_id=? ORDER BY seq DESC LIMIT 1',
                                (e['session_id'],)).fetchone()
                latest = json.loads(row[0])
                result.append(dict(pid=p.pid,created_at=created,version=e['code_version'],
                    session_id=e['session_id'],last_activity=latest['event_time_utc']))
            except psutil.NoSuchProcess:
                continue
    return result


def stop_tree(pid, created_at, timeout=5):
    """Stop only the verified owned process tree. No liquidation is requested."""
    try:
        parent = psutil.Process(pid)
        if abs(parent.create_time()-created_at) > .01:
            return False
        children = parent.children(recursive=True)
        targets = list(reversed(children)) + [parent]
        for p in targets:
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(targets, timeout=timeout)
        for p in alive:
            p.kill()
        _, alive = psutil.wait_procs(alive, timeout=timeout)
        return not alive
    except psutil.NoSuchProcess:
        return True
