"""Consistent stopped-ledger backup. Never deletes source records."""
import argparse
import sqlite3
import json
from datetime import datetime,timezone
from src.core.observability.events import ROOT
from src.core.observability.processes import Singleton
from src.markets.crypto.runtime import storage_path


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    args=p.parse_args()
    from pathlib import Path
    source=storage_path(ROOT);out=Path(args.output).resolve()
    lock=Singleton(source,'crypto:upbit:shadow')
    if not lock.acquire():raise RuntimeError('STOP_DAEMON_BEFORE_BACKUP')
    try:
        out.mkdir(parents=True,exist_ok=False)
        manifest={}
        for path in (source/'data').glob('*.db'):
            origin=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
            target=sqlite3.connect(out/path.name)
            try:
                origin.backup(target)
                integrity=target.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity!='ok':raise RuntimeError('BACKUP_INTEGRITY_FAILURE')
                manifest[path.name]=dict(integrity=integrity,tables={r[0]:target.execute('SELECT count(*) FROM "'+r[0].replace('"','""')+'"').fetchone()[0]
                    for r in target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()})
            finally:origin.close();target.close()
        (out/'manifest.json').write_text(json.dumps(dict(created_at=datetime.now(timezone.utc).isoformat(),databases=manifest),indent=2),encoding='utf8')
    finally:lock.close()

if __name__=='__main__':main()
