#!/usr/bin/env python3
"""Install both self-contained research skills; preserve previous installs as backups."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("archa-research-map", "archa-task-brief")


def install(destination: Path) -> dict:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location(
        "archa_initialize", ROOT / "skills/archa-research-map/scripts/initialize.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    backups = []
    with tempfile.TemporaryDirectory(prefix="archa-skills-") as temp:
        stage = Path(temp)
        for name in NAMES:
            shutil.copytree(ROOT / "skills" / name, stage / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "assets"))
        runtime = stage / NAMES[0] / "assets/runtime"
        module.snapshot(ROOT, runtime)
        module.verify(runtime)
        for name in NAMES:
            target = destination / name
            if target.exists() or target.is_symlink():
                backup_root = destination.parent / "skill-backups"
                backup_root.mkdir(exist_ok=True)
                backup = Path(tempfile.mkdtemp(
                    prefix=name + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-",
                    dir=backup_root)) / name
                target.rename(backup)
                backups.append(str(backup))
            try:
                shutil.copytree(stage / name, target)
            except OSError:
                if target.exists():
                    shutil.rmtree(target)
                if backups and Path(backups[-1]).name == name:
                    Path(backups[-1]).rename(target)
                raise
    return {"installed": [str(destination / name) for name in NAMES], "backups": backups}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills")
    args = parser.parse_args()
    print(json.dumps(install(args.destination), ensure_ascii=False, indent=2))