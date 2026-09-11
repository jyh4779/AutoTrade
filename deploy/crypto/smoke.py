"""Offline portability checks; no HTTP requests or persistent trading data."""
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from src.core.observability.processes import Singleton
from src.markets.crypto.research import Research


with tempfile.TemporaryDirectory() as d:
    a=Singleton(d,'portability');b=Singleton(d,'portability')
    assert a.acquire()
    assert not b.acquire()
    a.close();assert b.acquire();b.close()
    ledger=Research(Path(d)/'research.db')
    assert ledger.feedback()['automatic_weight_changes'] is False
    if os.name!='nt':
        # Execute daemon lifecycle with offline stubs and stop via the service signal.
        code="""
import sys,time
from pathlib import Path
from src.runners import crypto_daemon as m
m.run=lambda root:(Path(root)/'offline.json',{'status':'PASS'})
m.monitor=lambda root,**kwargs:{'at':m.datetime.now(m.timezone.utc).isoformat(),'status':'PASS'}
sys.argv=['offline','--root',sys.argv[1]]
raise SystemExit(m.main())
"""
        env=dict(os.environ,ML_CRYPTO_DATA=str(Path(d)/'state'))
        proc=subprocess.Popen([sys.executable,'-c',code,d],env=env)
        try:
            import time,json
            status=Path(env['ML_CRYPTO_DATA'])/'reports/daemon.json'
            for _ in range(100):
                if status.exists():break
                time.sleep(.05)
            assert status.exists()
            proc.send_signal(signal.SIGTERM)
            assert proc.wait(timeout=10)==0
            assert json.loads(status.read_text())['state']=='STOPPED'
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
print('Offline portability checks passed')
