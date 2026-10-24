"""Run only synthetic, isolated checks in the actual AstrBot runtime."""
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
checks=[['-m','unittest','discover','-s','tests','-v'],['tests/integration_runtime.py'],['tests/integration_memoria.py'],['tests/reply_delay_runtime.py'],['tools/deploy_legacy.py','--rehearse'],['tests/integration_social.py'],['tests/integration_reactions.py'],['tests/integration_leisure.py'],['tests/integration_extensions.py'],['tests/reply_chunks_runtime.py']]
for args in checks:
    r=subprocess.run([sys.executable]+args,cwd=root)
    if r.returncode: raise SystemExit(r.returncode)
print('ALL_RUNTIME_GATES_PASSED')
