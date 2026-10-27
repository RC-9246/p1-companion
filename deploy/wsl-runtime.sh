#!/usr/bin/env bash
# Foreground command for a dedicated Windows wsl.exe client. No GUI or bot API.
set -eu
STATE=/run/p1-companion-runtime
install -d -m 0700 "$STATE"
if [ "${1:-}" = --check ] || [ "${1:-}" = --stop ]; then
  exec python3 - "$STATE" "$1" <<'PY'
from pathlib import Path
import json,os,signal,sys
state=Path(sys.argv[1]);valid=False
try:
 p=state/'process.json';s=p.lstat();assert not p.is_symlink() and s.st_uid==0 and not s.st_mode&0o077
 v=json.loads(p.read_text());pid=v['pid'];assert type(pid) is int and pid>1
 proc=Path('/proc',str(pid));fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
 valid=(v['boot']==Path('/proc/sys/kernel/random/boot_id').read_text().strip() and fields[19]==v['start'] and
        (proc/'cmdline').read_bytes()==b'/usr/bin/sleep\0infinity\0' and (proc/'fd/9').resolve()==state/'lock')
except (OSError,ValueError,KeyError,AssertionError,IndexError,TypeError):pass
if sys.argv[2]=='--stop':
 if valid:os.kill(pid,signal.SIGTERM)
 sys.exit(0)
print('ready' if valid else 'not_ready');sys.exit(0 if valid else 1)
PY
fi
exec 9>"$STATE/lock"
flock --exclusive --nonblock 9 || exit 1
python3 - "$STATE" "$$" <<'PY'
from pathlib import Path
import json,os,sys
p=Path(sys.argv[1])/'process.json';pid=int(sys.argv[2]);fields=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
tmp=p.with_suffix('.next');tmp.write_text(json.dumps({'pid':pid,'start':fields[19],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}));tmp.chmod(0o600);os.replace(tmp,p)
PY
exec /usr/bin/sleep infinity
