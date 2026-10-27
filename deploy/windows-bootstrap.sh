#!/usr/bin/env bash
set -eu
DEST=/opt/p1-companion-installer
STATE=/var/lib/p1-companion-installer
if [ "${1:-}" = --start ]; then
  [ "$(cat /proc/1/comm)" = systemd ] || { echo 'WSL systemd 尚未启动，请更新 WSL 后重试'; exit 1; }
  install -d -m 0700 "$STATE"
  cd "$DEST"
  export PYTHONDONTWRITEBYTECODE=1
  exec python3 deploy/wizard.py --url-file "$STATE/browser.url" >"$STATE/launcher.log" 2>&1
fi
SOURCE=${1:?需要完整源码目录}
[ -f "$SOURCE/source-manifest.json" ] && [ -f "$SOURCE/deploy/wizard.py" ]
# Do not replace a server's source during a running installation.
if [ -f "$STATE/server.pid" ] && kill -0 "$(cat "$STATE/server.pid")" 2>/dev/null; then
  echo '向导仍在运行，请使用现有浏览器页面'; exit 1
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 ca-certificates
python3 - "$SOURCE" "$DEST" <<'PY'
from pathlib import Path
import hashlib,json,shutil,sys
source=Path(sys.argv[1]);dest=Path(sys.argv[2]);manifest=json.loads((source/'source-manifest.json').read_text())
assert not dest.is_symlink()
if dest.exists():assert (dest/'.p1-wizard-source').is_file(),'existing_directory_not_managed'
# Check everything before copying anything; preserve LF on Windows checkout.
contents={}
for rel,digest in manifest.items():
 p=source/rel;assert not Path(rel).is_absolute() and '..' not in Path(rel).parts and not p.is_symlink()
 raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==digest,'source_hash_mismatch';contents[rel]=raw
dest.mkdir(mode=0o755,parents=True,exist_ok=True)
for rel,raw in {**contents,'source-manifest.json':(source/'source-manifest.json').read_bytes()}.items():
 p=dest/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);p.chmod(0o644)
(dest/'.p1-wizard-source').write_text('1\n')
# Runtime holder survives removal of the temporary installer copy. Refuse to
# replace an unrecognized helper; never copy arbitrary paths from the browser.
runtime=Path('/usr/local/lib/p1-companion');runtime.mkdir(mode=0o755,parents=True,exist_ok=True)
assert not runtime.is_symlink() and runtime.stat().st_uid==0 and not runtime.stat().st_mode&0o022
helper=runtime/'wsl-runtime.sh';receipt=runtime/'wsl-runtime.sha256'
raw=contents['deploy/wsl-runtime.sh'];digest=hashlib.sha256(raw).hexdigest()
if helper.exists():
 assert not helper.is_symlink() and not receipt.is_symlink() and receipt.is_file() and hashlib.sha256(helper.read_bytes()).hexdigest()==receipt.read_text().strip(),'runtime_helper_modified'
helper.write_bytes(raw);helper.chmod(0o700);receipt.write_text(digest+'\n');receipt.chmod(0o600)
# Merge just the boot setting; do not overwrite automount, networking or interop.
p=Path('/etc/wsl.conf');original=p.read_text() if p.exists() else '';lines=original.splitlines();result=[];boot=False;set_value=False;seen_boot=False
for line in lines:
 if line.strip().startswith('['):
  if boot and not set_value:result.append('systemd=true');set_value=True
  boot=line.strip().lower()=='[boot]';seen_boot=seen_boot or boot
 if boot and line.split('=',1)[0].strip().lower()=='systemd':result.append('systemd=true');set_value=True
 else:result.append(line)
if boot and not set_value:result.append('systemd=true')
if not seen_boot:result+=['','[boot]','systemd=true']
if p.exists() and not Path('/etc/wsl.conf.p1-before').exists():shutil.copy2(p,'/etc/wsl.conf.p1-before')
p.write_text('\n'.join(result)+'\n')
PY
