#!/usr/bin/env python3
"""Install a project-local ArcHa snapshot without replacing existing contracts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

LAUNCHER = '''#!/usr/bin/env python3
"""Run the ArcHa snapshot stored next to this file."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "runtime"))
from opc.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
'''


def redirected(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Explicit deployment boundary: CLI, execution engine, workers, built-in strategy,
# scaffold resources and license. New repository files are not deployed implicitly.
RUNTIME_FILES = (
    "LICENSE",
    "opc/__init__.py",
    "opc/__main__.py",
    "opc/adapters/__init__.py",
    "opc/adapters/codex.py",
    "opc/adapters/dsh.py",
    "opc/adapters/prompts.py",
    "opc/adapters/scripted.py",
    "opc/adapters/worker.py",
    "opc/cli.py",
    "opc/core/__init__.py",
    "opc/core/accept.py",
    "opc/core/config.py",
    "opc/core/worker_config.py",
    "opc/core/engine.py",
    "opc/core/ledger.py",
    "opc/core/model.py",
    "opc/core/platform.py",
    "opc/core/windows.py",
    "opc/core/promote.py",
    "opc/core/workspace.py",
    "opc/domain.py",
    "opc/domains/__init__.py",
    "opc/domains/command.py",
    "opc/scaffold/__init__.py",
    "opc/scaffold/brief.py",
    "opc/scaffold/evaluate_template.py",
    "opc/scaffold/onboard.py",
    "opc/scaffold/workers.json",
    "opc/strategies/__init__.py",
    "opc/strategies/param_search.py",
    "opc/scaffold/ONBOARDING.md",
)


def snapshot(source: Path, target: Path) -> None:
    """Package only the runtime allowlist; identify actual bytes separately from HEAD."""
    files = [source / rel for rel in RUNTIME_FILES]
    missing = [str(p.relative_to(source)) for p in files if not p.is_file()]
    if missing:
        raise ValueError("missing runtime files: " + ", ".join(missing))
    for path in files:
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    proc = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    hashes = {rel: digest(target / rel) for rel in RUNTIME_FILES}
    differs = []
    if proc.returncode == 0:
        # Ask git whether a path differs from HEAD. Comparing raw working-tree bytes
        # to blob bytes reports every CRLF checkout as uncommitted, so a clean source
        # tree would be recorded as a dirty snapshot identity.
        changed = subprocess.run(["git", "-C", str(source), "diff", "--name-only", "-z",
                                  "HEAD", "--"], capture_output=True)
        changed_paths = {p for p in changed.stdout.decode("utf-8", "surrogateescape").split("\0")
                         if p}
        for rel in RUNTIME_FILES:
            tracked = subprocess.run(["git", "-C", str(source), "cat-file", "-e", "HEAD:" + rel],
                                     capture_output=True)
            if tracked.returncode or rel in changed_paths:
                differs.append(rel)
    manifest = {"format": 1, "source_commit": proc.stdout.strip() if proc.returncode == 0 else None,
                "source_kind": "working-tree snapshot; source_commit is a base, not the bundle identity",
                "differs_from_head": differs if proc.returncode == 0 else None,
                "snapshot_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
                "files": hashes}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def verify(runtime: Path) -> dict:
    if redirected(runtime):
        raise ValueError("runtime must be a local directory, not a symlink")
    manifest = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1 or not manifest.get("files"):
        raise ValueError("unsupported or empty runtime manifest")
    for rel, expected in manifest["files"].items():
        path = runtime / rel
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(runtime.resolve()):
            raise ValueError("runtime manifest path escapes snapshot: " + rel)
        if not path.is_file() or digest(path) != expected:
            raise ValueError("runtime file missing or modified: " + rel)
    actual = {p.relative_to(runtime).as_posix() for p in runtime.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("runtime contains files absent from manifest")
    return manifest


def initialize(project: Path, runtime: Path) -> dict:
    project = project.resolve()
    if not project.is_dir():
        raise ValueError("project must be an existing directory")
    verify(runtime)
    control = project / ".opc"
    if redirected(control) or any(p.name.casefold() == ".opc" and p.name != ".opc"
                                   for p in project.iterdir()):
        raise ValueError(".opc is redirected or has a case-conflicting name")
    existing = control.exists()
    config_path = control / "project.json"
    if existing:
        if not control.is_dir():
            raise ValueError(".opc must be a directory")
        if redirected(config_path):
            raise ValueError("project.json must not be a symlink")
        if not config_path.is_file() and not (control / "runtime").is_dir():
            raise ValueError("existing .opc is neither a deployed runtime nor a project scaffold")
    local_runtime = control / "runtime"
    if redirected(local_runtime):
        raise ValueError("existing runtime is a symlink")
    if local_runtime.exists():
        verify(local_runtime)  # Resume pinned version, even when skill carries a newer one.
    launcher = control / "archa.py"
    if redirected(launcher) or (launcher.exists() and launcher.read_text(encoding="utf-8") != LAUNCHER):
        raise ValueError("existing .opc/archa.py conflicts with project-local launcher")
    if not existing:
        control.mkdir()
    if not local_runtime.exists():
        # Stage inside .opc, so interruption cannot expose a partial runtime.
        # TemporaryDirectory uses mode 0700. On Windows/Python 3.13+ its
        # private ACL survives rename and makes runtime unreadable to workers
        # running as the sandbox account. Inherit the project's ACL instead.
        staging = control / (".runtime-" + uuid.uuid4().hex)
        staging.mkdir()
        try:
            staged = staging / "runtime"
            shutil.copytree(runtime, staged)
            verify(staged)
            staged.rename(local_runtime)
        finally:
            shutil.rmtree(staging)
    if not launcher.exists():
        with launcher.open("x") as stream:
            stream.write(LAUNCHER)
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    return {"project": str(project), "existing_scaffold": config_path.exists(),
            "execution_enabled": config.get("execution_enabled", False),
            "runtime_commit": verify(local_runtime)["source_commit"],
            "entrypoint": str(launcher), "next": "discuss research map; no experiments started"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    skill = Path(__file__).resolve().parents[1]
    bundle = skill / "assets/runtime"
    try:
        if bundle.is_dir():
            result = initialize(args.project, bundle)
        else:
            source = skill.parent.parent
            if not (source / "opc/cli.py").is_file():
                raise ValueError("runtime bundle missing; reinstall with tools/install_research_skills.py")
            with tempfile.TemporaryDirectory(prefix="archa-source-") as temp:
                snapshot(source, Path(temp))
                result = initialize(args.project, Path(temp))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print("initialization failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
