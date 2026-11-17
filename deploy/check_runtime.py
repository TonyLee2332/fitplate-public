"""Fail early if the shared AI configuration or writable data path is missing."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def check():
    from fitplate.model_client import load_config
    from fitplate.visitors import signing_key
    load_config()
    configured=os.environ.get('FITPLATE_DATA_DIR')
    if not configured:
        raise RuntimeError('Set FITPLATE_DATA_DIR to /var/data/fitplate and attach the persistent disk at /var/data.')
    path=Path(configured)
    if not path.is_absolute():
        raise RuntimeError('FITPLATE_DATA_DIR must be an absolute persistent data path.')
    path.mkdir(parents=True,exist_ok=True)
    signing_key()
    print('FitPlate server configuration and data directory are ready. Verify the disk mount in Render.')


if __name__=='__main__':
    try:
        check()
    except Exception:
        print('Startup configuration failed. Check the three AI settings, FITPLATE_DATA_DIR and the attached disk in Render.',file=sys.stderr)
        raise SystemExit(1)
