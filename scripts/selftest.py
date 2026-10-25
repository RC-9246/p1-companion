"""Offline core tests; no models, QQ, production DBs or account state."""
import os,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
# Production image/character-specific tests are preserved for reference but require
# separately supplied reviewed assets. This suite checks the neutral core only.
suites=['test_companion','test_agency','test_resilience','test_emotion_model','test_emotional_quality','test_learning','test_self_response','test_media_grounding','test_quick_provider']
r=subprocess.run([sys.executable,'-m','unittest',*[name for name in suites]],cwd=R/'tests',env={**os.environ,'PYTHONPATH':str(R/'tests')+os.pathsep+str(R/'release')});raise SystemExit(r.returncode)
