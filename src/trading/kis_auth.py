"""Compatibility entry point; implementation lives in src.adapters.kis.kis_auth."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if __name__ == '__main__':
    import runpy
    runpy.run_module('src.adapters.kis.kis_auth', run_name='__main__')
else:
    import importlib
    sys.modules[__name__] = importlib.import_module('src.adapters.kis.kis_auth')
