#!/usr/bin/env bash
set -euo pipefail
python deploy/check_runtime.py
exec python -m streamlit run app.py --server.address 0.0.0.0 --server.port "${PORT:-10000}" --server.headless true --server.runOnSave false --server.fileWatcherType none --browser.gatherUsageStats false
