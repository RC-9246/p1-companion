import copy,json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'))
from astrbot_plugin_affect.emotion_model import seed,context,describe
from astrbot_plugin_affect.context_style import style_context
from astrbot_plugin_affect.companion_store import BASE
from astrbot_plugin_affect.relationship_style import PROFILE_LABEL

class RelationshipPresentationTests(unittest.TestCase):
 def test_warm_presentation_does_not_forge_recorded_relationship(self):
  s=seed();before=copy.deepcopy(s);legacy=dict(BASE)
  text=context(s,[],{});hint=style_context(legacy,{})
  self.assertIn(PROFILE_LABEL,text);self.assertIn(PROFILE_LABEL,hint)
  self.assertEqual(s,before);self.assertEqual(legacy,BASE)
  self.assertEqual(s['familiarity'],0);self.assertEqual(s['interactions'],0)
  self.assertEqual(describe(s)['relationship'],'谨慎熟悉')
 def test_standalone_mcp_import_remains_supported(self):
  code='import sys;sys.path.insert(0,sys.argv[1]);import companion_store;from emotion_model import seed,context;assert context(seed(),[],{});print("standalone_import_ok")'
  r=subprocess.run([sys.executable,'-c',code,str(ROOT/'release/astrbot_plugin_affect')],capture_output=True,text=True,timeout=10)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIn('standalone_import_ok',r.stdout)
if __name__=='__main__':unittest.main()
