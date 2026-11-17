#!/usr/bin/env bash
set -euo pipefail
python -m pip install --disable-pip-version-check --no-cache-dir 'torch==2.15.0+cpu' --index-url https://download.pytorch.org/whl/cpu
python -m pip install --disable-pip-version-check --no-cache-dir -r requirements-lock.txt
python -m pip check
python -m fitplate.install_depth
