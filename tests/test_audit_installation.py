"""Reviewed overlays, explicit service adoption and installer continuity."""
import hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_modules as CM
import test_core_updater as CU
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'deploy'))
import asset_pack as A
from neutral_assets import catalog

class LayoutTests(unittest.TestCase):
 def test_installer_overlay_requires_committed_matching_job(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve()/'agent';point=root/'backups/oneclick-20261029-fixture';point.mkdir(parents=True)
   p=point/'companion-override.json';p.write_text(json.dumps({'services':{'astrbot':{'image':'fixture','networks':['control']}}}))
   labels={'com.docker.compose.service':'astrbot','com.docker.compose.project.config_files':str(root/'astrbot/compose.yaml')+','+str(p)}
   self.assertFalse(CU.U.core_compose_layout(root,'astrbot',labels))
   (point/'state.json').write_text(json.dumps({'root':str(root),'status':'committed'}));self.assertTrue(CU.U.core_compose_layout(root,'astrbot',labels))
   p.write_text(json.dumps({'services':{'astrbot':{'privileged':True}}}));self.assertFalse(CU.U.core_compose_layout(root,'astrbot',labels))
 def test_foreign_service_needs_explicit_frozen_adoption(self):
  c=CM.CompositionTests();c.setUp();self.addCleanup(c.doCleanups)
  foreign=c.root.parent/'external-compose.yaml';foreign.write_text('services: {}')
  obj=c.d.items['p1-browser'];obj['Config']['Labels']['com.docker.compose.project.config_files']=str(foreign)
  with self.assertRaisesRegex(CM.M.ModuleError,'foreign_module'):c.c.binding('p1-browser',obj)
  r=c.c.adopt_existing(['p1-browser']);self.assertFalse(r['runtime_changed']);self.assertEqual(c.c.binding('p1-browser',obj),obj)
  obj['Image']='sha256:'+'e'*64
  with self.assertRaisesRegex(CM.M.ModuleError,'foreign_module'):c.c.binding('p1-browser',obj)
 def test_arbitrary_container_cannot_be_adopted(self):
  c=CM.CompositionTests();c.setUp();self.addCleanup(c.doCleanups)
  with self.assertRaisesRegex(CM.M.ModuleError,'service_denied'):c.c.adopt_existing(['other-service'])

class AssetPackTests(unittest.TestCase):
 def test_register_install_restart_and_source_integrity(self):
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp).resolve();fixture=catalog(base/'fixture');row=A.Catalog(fixture).assets['saki_fixture_portrait'];raw=(fixture/'reaction_assets'/row['file']).read_bytes()
   original=(R/'release/astrbot_plugin_affect/reactions.json').read_bytes();result=A.add_image(base/'private-pack',raw,'.png','合成测试',['合成'],'其他',True)
   data=base/'data';data.mkdir();A.install_pack(base/'private-pack',data)
   from astrbot_plugin_affect.reactions import catalog_folder
   self.assertEqual(len(A.Catalog(catalog_folder(R/'release/astrbot_plugin_affect',data)).assets),1)
   self.assertEqual(A.Catalog(data/'reviewed_assets').read(result['id']),raw)
   self.assertEqual((R/'release/astrbot_plugin_affect/reactions.json').read_bytes(),original)
   with self.assertRaisesRegex(ValueError,'already_installed'):A.install_pack(base/'private-pack',data)
 def test_unreviewed_and_symlink_pack_denied(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();fixture=catalog(p/'fixture');raw=A.Catalog(fixture).read('saki_fixture_portrait')
   with self.assertRaisesRegex(ValueError,'review'):A.add_image(p/'pack',raw,'.png','合成',['合成'],'其他',False)
   (p/'pack').symlink_to(fixture,target_is_directory=True)
   with self.assertRaisesRegex(ValueError,'symlink'):A.install_pack(p/'pack',p/'runtime')

if __name__=='__main__':unittest.main()
