#!/usr/bin/env python3
"""Private agency backup without temporary document data or temporary derivatives."""
import json,os,re,shutil,sqlite3,time
from contextlib import closing
from pathlib import Path
BASE=Path('/srv/p1-agent');ROOT=BASE/'astrbot/data/plugin_data/affect/agency'
def backup(root=ROOT,destination=None):
 if not (root/'agency.db').is_file():return None
 os.umask(0o077);point=destination or BASE/'backups/agency-daily'/time.strftime('%Y%m%d-%H%M%S');point.mkdir(mode=0o700,parents=True)
 with closing(sqlite3.connect('file:'+str(root/'agency.db')+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(point/'agency.db')) as target:
  source.backup(target);target.execute('PRAGMA secure_delete=ON')
  with target:
   target.execute('DELETE FROM document')
   for table in ('artifact','task','event'):target.execute('DELETE FROM '+table+' WHERE expires>0')
   # Audit may contain an artifact reference, never a raw file body.
   target.execute('DELETE FROM topic')
  target.execute('VACUUM');assert target.execute('PRAGMA quick_check').fetchone()[0]=='ok'
  target.row_factory=sqlite3.Row
  import hashlib
  for row in target.execute('SELECT id,scope,format FROM artifact WHERE expires=0'):
   if not re.fullmatch('[0-9a-f]{24}',row['id']) or row['format'] not in ('md','txt','csv','json','html'):continue
   folder=hashlib.sha256(row['scope'].encode()).hexdigest();source=root/folder/(row['id']+'.'+row['format'])
   if source.is_file() and not source.is_symlink():
    dest=point/folder/source.name;dest.parent.mkdir(mode=0o700,exist_ok=True);shutil.copy2(source,dest);dest.chmod(0o600)
 (point/'agency.db').chmod(0o600);return point
if __name__=='__main__':backup()
