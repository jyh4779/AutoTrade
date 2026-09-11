"""Deployment paths independent of the source tree."""
import os
from pathlib import Path


def storage_path(root):
    return Path(os.environ.get('ML_CRYPTO_DATA', str(Path(root)/'data/crypto/upbit'))).expanduser().resolve()
