"""Compatibility entry point; implementation lives in src.runners.stock_liquidation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if __name__ == '__main__':
    import runpy
    runpy.run_module('src.runners.stock_liquidation', run_name='__main__')
else:
    import importlib
    sys.modules[__name__] = importlib.import_module('src.runners.stock_liquidation')
