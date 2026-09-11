"""Build a code-only allowlisted package. No account files, databases or stock adapters."""
from pathlib import Path
import zipfile
import json
import hashlib

ROOT=Path(__file__).resolve().parents[2]
ALLOW=[
 'src/__init__.py','src/adapters/__init__.py','src/adapters/upbit',
 'src/core/__init__.py','src/core/observability/__init__.py',
 'src/core/observability/events.py','src/core/observability/processes.py',
 'src/core/research','src/markets/__init__.py','src/markets/crypto',
 'src/runners/__init__.py','src/runners/crypto.py','src/runners/crypto_daemon.py',
 'src/reporting/__init__.py','src/reporting/crypto_feedback.py',
 'src/reporting/crypto_health.py','src/runners/crypto_backup.py']

def build():
    files=set()
    for name in ALLOW:
        path=ROOT/name
        files.update(path.rglob('*.py') if path.is_dir() else [path])
    files.update((ROOT/'deploy/crypto').glob('*'))
    files={p for p in files if p.is_file()}
    out=ROOT/'dist/crypto-ubuntu.zip';out.parent.mkdir(exist_ok=True)
    manifest={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files):z.write(p,p.relative_to(ROOT))
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    print(out)

if __name__=='__main__':build()
