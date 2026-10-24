import hashlib
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.inspect_p1 import docker_inventory, inventory


class InspectionSafetyTests(unittest.TestCase):
    def test_metadata_does_not_disclose_or_change_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "astrbot/data/plugins/astrbot_plugin_memoria"
            plugin.mkdir(parents=True)
            db = root / "astrbot/data/affect.sqlite3"
            db.write_bytes(b"PRIVATE CHAT AND SECRET TOKEN")
            Path(str(db) + "-wal").write_bytes(b"WAL SECRET")
            (plugin / "main.py").write_text('API_KEY = "HIDDEN_KEY"')
            (root / ".env").write_text("SECRET_PASSWORD")
            (root / "onebot_123456789.json").write_text("PRIVATE CONFIG")
            (root / "external").symlink_to(root.parent, target_is_directory=True)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            report = inventory(root)
            text = str(report)
            self.assertNotIn("PRIVATE", text)
            self.assertNotIn("HIDDEN_KEY", text)
            self.assertNotIn("SECRET_PASSWORD", text)
            self.assertNotIn("123456789", text)
            self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())
            self.assertTrue(any(x.get("sqlite_sidecars") == ["-wal"] for x in report["items"]))
            self.assertFalse(any("external" in x["path"] for x in report["items"]))

    def test_docker_errors_never_echo_sensitive_stderr(self):
        with patch("tools.inspect_p1.shutil.which", return_value="/usr/bin/docker"), patch(
            "tools.inspect_p1.subprocess.run"
        ) as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "PRIVATE_TOKEN"
            self.assertNotIn("PRIVATE_TOKEN", str(docker_inventory("astrbot")))
            command = run.call_args.args[0]
            self.assertNotIn(".Config.Env", command[command.index("--format") + 1])


if __name__ == "__main__":
    unittest.main()
