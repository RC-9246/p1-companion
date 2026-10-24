#!/usr/bin/env python3
"""Independent recovery of the maintenance mechanism, from a root-owned checkpoint."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,time
ROOT=Path('/var/lib/p1-companion/recovery/current')
FILES={'unit_p1-companion-maintain_service':Path('/etc/systemd/system/p1-companion-maintain.service'),'unit_p1-companion-maintain_timer':Path('/etc/systemd/system/p1-companion-maintain.timer'),'maintain':Path('/usr/local/sbin/p1-companion-maintain.py'),'resilience':Path('/usr/local/lib/p1-companion/resilience.py')}
def main():
 os.umask(0o077)
 if Path('/srv/p1-agent/astrbot/data/plugin_data/affect/maintenance.disabled').exists():return
 try:manifest=json.loads((ROOT/'fixed-manifest.json').read_text())
 except (OSError,ValueError):return
 fixed=[]
 for key,target in FILES.items():
  source=ROOT/'fixed'/key;expected=manifest.get(key)
  if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:return
  if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:continue
  target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+'.watchdog-next');shutil.copyfile(source,temp);temp.chmod(0o700);os.replace(temp,target);fixed.append(key)
 if any(x.startswith('unit_') for x in fixed):subprocess.run(['systemctl','daemon-reload'],capture_output=True,timeout=15)
 if fixed:subprocess.run(['systemctl','start','p1-companion-maintain.service'],capture_output=True,timeout=600)
 if not Path('/srv/p1-agent/astrbot/data/plugin_data/affect/maintenance.disabled').exists():subprocess.run(['systemctl','start','p1-companion-maintain.timer'],capture_output=True,timeout=15)
if __name__=='__main__':main()
