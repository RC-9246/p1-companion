"""Upgrade boundary tests; native upgrade/rollback is exercised in the Linux lab."""
import hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];FILE=R/('scripts' if (R/'scripts/upgrade_repair_chain.py').exists() else 'tools')/'upgrade_repair_chain.py'
s=importlib.util.spec_from_file_location('repair_upgrade',FILE);U=importlib.util.module_from_spec(s);s.loader.exec_module(U)
class UpgradeTests(unittest.TestCase):
 def test_dry_run_never_invokes_systemctl_or_docker(self):
  r=subprocess.run([sys.executable,str(FILE),'--root','/srv/p1-agent'],capture_output=True,text=True,timeout=5)
  self.assertEqual(r.returncode,0);self.assertTrue(json.loads(r.stdout)['dry_run']);self.assertFalse(json.loads(r.stdout)['bot_restart'])
 def test_broad_relative_and_shell_roots_denied(self):
  for root in ('/','/srv','relative','/srv/a/../b','/tmp/x;id'):
   with self.assertRaises(U.UpgradeError):U.root_path(root)
 def test_symlink_root_denied(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve();(p/'real').mkdir();(p/'link').symlink_to(p/'real')
   with self.assertRaises(U.UpgradeError):U.root_path(str(p/'link'))
 def test_only_three_known_watchdog_source_destinations(self):
  paths=U.sources(Path('/srv/test'));self.assertEqual(len(paths),3);self.assertEqual(paths[0],U.LIVE);self.assertTrue(all(p.name=='p1-companion-watchdog.py' for p in paths))
 def test_known_legacy_layout_uses_neutral_staging_copy(self):
  with tempfile.TemporaryDirectory() as t:
   base=Path(t);legacy=base/'astrbot/data/companion_neutral_v020_lab/services/maintenance/p1-companion-watchdog.py';legacy.parent.mkdir(parents=True);legacy.write_text('old')
   self.assertEqual(U.sources(base)[1],legacy)
 def test_standard_copy_takes_precedence_over_legacy(self):
  with tempfile.TemporaryDirectory() as t:
   base=Path(t);d=base/'astrbot/data'
   for p in [d/'companion_neutral_v020_lab/services/maintenance/p1-companion-watchdog.py',d/'companion_services/maintenance/p1-companion-watchdog.py']:p.parent.mkdir(parents=True);p.write_text('old')
   self.assertEqual(U.sources(base)[1],d/'companion_services/maintenance/p1-companion-watchdog.py')
 def test_tree_snapshot_rejects_symlinks(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve();(p/'link').symlink_to('/etc/hosts')
   with self.assertRaises(U.UpgradeError):U.tree_hashes(p)
 def test_intervening_checkpoint_file_change_blocks_auto_rollback(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve();(p/'fixed').mkdir();(p/'fixed/helper').write_text('old');(p/'fixed-manifest.json').write_text(json.dumps({'helper':'a','watchdog':'b'}));before=U.tree_hashes(p);info={'checkpoint_before':before,'old_fixed_manifest':U.read(p/'fixed-manifest.json')}
   with patch.object(U,'CURRENT',p):
    self.assertTrue(U.compatible_checkpoint(info));(p/'fixed/helper').write_text('legitimate newer code');self.assertFalse(U.compatible_checkpoint(info))
 def test_only_own_watchdog_manifest_entry_may_change(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve();(p/'fixed-manifest.json').write_text(json.dumps({'helper':'a','watchdog':'old'}));before=U.tree_hashes(p);info={'checkpoint_before':before,'old_fixed_manifest':U.read(p/'fixed-manifest.json')}
   with patch.object(U,'CURRENT',p):
    (p/'fixed-manifest.json').write_text(json.dumps({'helper':'a','watchdog':'new'}));self.assertTrue(U.compatible_checkpoint(info))
    (p/'fixed-manifest.json').write_text(json.dumps({'helper':'different','watchdog':'new'}));self.assertFalse(U.compatible_checkpoint(info))
 def test_failed_atomic_replace_preserves_original(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve()/'code';p.write_bytes(b'old')
   with patch.object(U.os,'replace',side_effect=OSError('simulated')):
    with self.assertRaises(OSError):U.atom(p,b'new',uid=os.getuid(),gid=os.getgid())
   self.assertEqual(p.read_bytes(),b'old');self.assertEqual(list(p.parent.glob('*.next')),[])
 def test_guard_cleanup_does_not_remove_changed_unit_file(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve();name='p1-repair-upgrade-123';service=p/(name+'.service');service.write_text('foreign changed unit');info={'guard':name,'guard_hashes':{'.service':hashlib.sha256(b'expected').hexdigest(),'.timer':'a'*64}}
   with patch.object(U,'UNITDIR',p),patch.object(U,'run',return_value=subprocess.CompletedProcess([],0)):
    with self.assertRaises(U.UpgradeError):U.cleanup_guard(p,info)
   self.assertEqual(service.read_text(),'foreign changed unit')
 def test_private_records_have_bounded_size(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'oversized';p.write_bytes(b'x'*262145)
   with self.assertRaises(U.UpgradeError):U.read(p)
if __name__=='__main__':unittest.main()
