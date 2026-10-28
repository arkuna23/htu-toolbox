#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
if [ ! -x .venv/bin/python ]; then
  echo '请先运行 python3 scripts/setup.py --install-only' >&2
  exit 1
fi
exec .venv/bin/python -m web.server --open-browser "$@"
