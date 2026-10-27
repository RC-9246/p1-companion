#!/usr/bin/env bash
# Guided, local installation. Does not download or pipe a remote script into sudo.
set -eu
HERE="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo '需要 Python 3.11+；请先安装 Python，再运行本脚本。' >&2
  exit 1
fi
exec python3 "$HERE/deploy/install.py" "$@"
