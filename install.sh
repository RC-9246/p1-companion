#!/usr/bin/env bash
# Local reviewed source only. Never curl a script into sudo.
set -eu
HERE="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
if [ "$(uname -s)" != Linux ]; then
  echo 'Windows 请双击 开始安装.cmd；此入口用于目标 Linux 主机。' >&2
  exit 1
fi
if [ "$(id -u)" != 0 ]; then exec sudo bash "$HERE/install.sh" "$@"; fi
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys;sys.exit(sys.version_info < (3,11))'; then
  . /etc/os-release
  case "${ID:-}:${VERSION_CODENAME:-}" in ubuntu:noble|debian:bookworm|debian:trixie|armbian:noble|armbian:bookworm|armbian:trixie) ;; *) echo '需要 Ubuntu 24.04 或 Debian 12/13，和 Python 3.11+' >&2; exit 1 ;; esac
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 ca-certificates
fi
exec python3 "$HERE/deploy/wizard.py" "$@"
