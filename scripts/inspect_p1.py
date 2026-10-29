#!/usr/bin/env python3
"""Bounded, metadata-only inventory. No config values, logs, DB rows or API calls."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

SKIP = {".git", ".ssh", ".aws", ".codex", ".agents", "node_modules",
        ".venv", "venv", "__pycache__", "logs", "log", "backups", "backup"}
INTEREST = re.compile(r"affect|memoria|knowledge|memory|astrbot|snowluma", re.I)
DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
MAX_ENTRIES = 15000
MAX_RESULTS = 160


def safe_path(path):
    # Mask QQ/account-like numeric identifiers in filenames and mount paths.
    return re.sub(r"(?<!\d)\d{5,}(?!\d)", "<number>", str(path))


def inventory(root):
    root = Path(root).expanduser()
    result = {"root": safe_path(root), "exists": root.is_dir(), "items": [],
              "limited": False, "permission_errors": 0}
    if not root.is_dir() or root.is_symlink():
        return result
    visited = 0

    def onerror(_):
        result["permission_errors"] += 1

    for parent, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        parent = Path(parent)
        depth = len(parent.relative_to(root).parts)
        visited += len(dirs) + len(files)
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith(".")
                         and not (parent / d).is_symlink()) if depth < 7 else []
        if visited > MAX_ENTRIES:
            result["limited"] = True
            break
        for name in sorted(dirs + files):
            p = parent / name
            if p.is_symlink():
                continue
            rel = p.relative_to(root)
            is_db = p.suffix.lower() in DB_SUFFIXES
            # List relevant code/plugin directories, DB files and compose locations.
            selected = is_db or (p.is_dir() and INTEREST.search(str(rel))) or (
                name in {"compose.yaml", "compose.yml", "docker-compose.yaml",
                         "docker-compose.yml"}) or (
                name in {"main.py", "metadata.yaml", "_conf_schema.json"}
                and INTEREST.search(str(rel)))
            if not selected:
                continue
            try:
                item = {"path": safe_path(rel),
                        "kind": "dir" if p.is_dir() else "file"}
                if p.is_file():
                    item["bytes"] = p.stat().st_size
                if is_db:
                    # Never open a production SQLite connection in this first pass.
                    item["sqlite_sidecars"] = [s for s in ("-wal", "-shm", "-journal")
                                                if Path(str(p) + s).exists()]
                result["items"].append(item)
            except OSError:
                result["permission_errors"] += 1
            if len(result["items"]) >= MAX_RESULTS:
                result["limited"] = True
                return result
    return result


def docker_inventory(name):
    docker = shutil.which("docker")
    if not docker:
        return {"container": name, "status": "docker_unavailable"}
    # Select fields before output; never request Env, command args or labels.
    fmt = ('{"image":{{json .Config.Image}},"working_dir":{{json .Config.WorkingDir}},'
           '"running":{{json .State.Running}},"mounts":{{json .Mounts}},'
           '"ports":{{json .NetworkSettings.Ports}}}')
    try:
        run = subprocess.run([docker, "container", "inspect", "--format", fmt, name],
                             capture_output=True, text=True, timeout=6, check=False)
        if run.returncode:
            return {"container": name, "status": "unavailable_or_no_permission"}
        raw = json.loads(run.stdout)
        # Image names can contain registry usernames; report a fingerprint instead.
        return {"container": name, "status": "inspected", "running": raw["running"],
                "image_ref_sha256": hashlib.sha256(raw["image"].encode()).hexdigest(),
                "working_dir": safe_path(raw["working_dir"]),
                "mounts": [{"type": m.get("Type"), "source": safe_path(m.get("Source", "")),
                            "destination": safe_path(m.get("Destination", "")),
                            "rw": m.get("RW")} for m in raw.get("mounts", [])],
                "port_bindings": {port: [{"host_ip": b.get("HostIp"),
                                           "host_port": b.get("HostPort")} for b in binds or []]
                                  for port, binds in (raw.get("ports") or {}).items()}}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return {"container": name, "status": "inspection_failed"}


def protected_files():
    entries = []
    for base, pattern in ((Path("/usr/local/sbin"), "p1-*"),
                          (Path("/etc/systemd/system"), "p1-*")):
        for p in sorted(base.glob(pattern)):
            if p.is_symlink() or not p.is_file():
                continue
            try:
                if p.stat().st_size > 1024 * 1024:
                    continue
                entries.append({"path": safe_path(p),
                                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
            except OSError:
                entries.append({"path": safe_path(p), "status": "unreadable"})
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path.home() / "p1-agent"))
    parser.add_argument("--no-docker", action="store_true")
    args = parser.parse_args()
    report = {"format": "p1-affect-preflight-v1", "mode": "metadata_only",
              "project": inventory(args.root), "protected_file_fingerprints": protected_files(),
              "containers": [] if args.no_docker else [docker_inventory(n) for n in ("astrbot", "snowluma")],
              "not_collected": ["credentials", "config_values", "logs", "chat_messages",
                                "database_rows", "database_schema", "api_responses"]}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
