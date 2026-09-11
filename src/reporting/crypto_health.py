"""Read-only liveness and disk checks; nonzero means operator attention required."""
import json
import shutil
from datetime import datetime,timezone
import psutil
from src.core.observability.events import ROOT
from src.markets.crypto.runtime import storage_path


def check(storage):
    state=json.loads((storage/'reports/daemon.json').read_text(encoding='utf8'))
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['at'])).total_seconds()
    alive=False
    try:
        proc=psutil.Process(state['pid'])
        alive='src.runners.crypto_daemon' in proc.cmdline()
    except psutil.Error:pass
    free=shutil.disk_usage(storage).free
    ok=alive and state['state']=='RUNNING' and 0<=age<90 and free>1_000_000_000
    return dict(status='PASS' if ok else 'FAIL',process_alive=alive,age_seconds=age,
                free_bytes=free,monitoring_status=state.get('monitoring_status'))

if __name__=='__main__':
    try:result=check(storage_path(ROOT))
    except Exception as exc:result=dict(status='FAIL',error=type(exc).__name__)
    print(json.dumps(result))
    raise SystemExit(0 if result['status']=='PASS' else 2)
