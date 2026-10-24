"""Persistent 8-hour ceiling within the unified 5-8h activity budget Shanghai-day watch budget; interrupted unknown reservations persist."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import math,secrets,sqlite3,time
from zoneinfo import ZoneInfo
LIMIT=28800
class Quota:
 def __init__(self,path):
  self.path=Path(path)
  with closing(sqlite3.connect(self.path)) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS watch_quota(id TEXT PRIMARY KEY, day TEXT NOT NULL, reserved INTEGER NOT NULL, state TEXT NOT NULL, started REAL NOT NULL)')
  self.path.chmod(0o600)
 def day(self,now):return datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
 def remaining(self,now):
  with closing(sqlite3.connect(self.path)) as db:
   used=db.execute('SELECT COALESCE(SUM(reserved),0) FROM watch_quota WHERE day=?',(self.day(now),)).fetchone()[0]
  return max(0,LIMIT-used)
 def reserve(self,seconds,now):
  if type(seconds) is not int or not 10<=seconds<=900:raise ValueError('duration_limit')
  key=secrets.token_hex(12)
  with closing(sqlite3.connect(self.path,timeout=3)) as db,db:
   db.execute('BEGIN IMMEDIATE')
   used=db.execute('SELECT COALESCE(SUM(reserved),0) FROM watch_quota WHERE day=?',(self.day(now),)).fetchone()[0]
   if used+seconds>LIMIT:raise ValueError('daily_8_hour_limit')
   db.execute('INSERT INTO watch_quota VALUES(?,?,?,?,?)',(key,self.day(now),seconds,'reserved',now))
   db.execute('DELETE FROM watch_quota WHERE started<?',(now-86400*32,))
  return key
 def finish(self,key,elapsed,state):
  if state not in ('completed','cancelled','blocked'):raise ValueError('invalid_finish')
  if not math.isfinite(elapsed) or elapsed<0:raise ValueError('invalid_clock')
  with closing(sqlite3.connect(self.path,timeout=3)) as db,db:
   db.execute('UPDATE watch_quota SET reserved=MIN(reserved,?),state=? WHERE id=? AND state=?',(int(math.ceil(elapsed)),state,key,'reserved'))
