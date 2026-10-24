"""Verify the distributed source manifest without network access or runtime reads."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'source-manifest.json').read_text())
assert isinstance(manifest,dict) and manifest
for rel,expected in manifest.items():
 path=root/rel
 assert not path.is_symlink() and path.resolve().is_relative_to(root.resolve()) and path.is_file(),rel
 assert hashlib.sha256(path.read_bytes()).hexdigest()==expected,rel
print(json.dumps({'source_files_verified':len(manifest),'network_calls':0,'runtime_data_read':False}))
