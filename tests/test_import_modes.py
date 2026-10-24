"""The native MCP subprocess imports the shared store outside the plugin package."""
import sys,subprocess,json,unittest
from pathlib import Path
class ImportModes(unittest.TestCase):
 def test_standalone_native_mcp_store_import(self):
  root=Path(__file__).resolve().parents[1]/'release/astrbot_plugin_affect'
  code="import sys;sys.path.insert(0,"+repr(str(root))+");from companion_store import CompanionStore;from emotion_model import seed,validate;validate(seed());print('standalone_ok')"
  r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=10)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIn('standalone_ok',r.stdout)
