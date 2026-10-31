"""Stage worker-visible DMA inputs in a fresh independent Git project; no model calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def git(*args, cwd):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def prepare(destination):
    destination = Path(destination).resolve()
    # mkdir is exclusive: a repeated run must never overwrite evidence.
    destination.mkdir(parents=True, exist_ok=False)
    project = destination / "project"
    project.mkdir()
    for name in ("workspaces", "acceptance", "logs"):
        (destination / name).mkdir()
    inputs = {}
    for source in [HERE / "TASK.md", *sorted((HERE / "starter").iterdir())]:
        if not source.is_file() or source.suffix == ".pyc":
            continue
        shutil.copyfile(source, project / source.name)
        inputs[str(source.relative_to(HERE))] = hashlib.sha256(source.read_bytes()).hexdigest()
    (project / ".gitignore").write_text("__pycache__/\n*.pyc\n.opc/local/\n", encoding="utf-8")
    git("init", "-b", "main", cwd=project)
    git("add", ".", cwd=project)
    git("-c", "user.name=ArcHa benchmark", "-c", "user.email=benchmark@localhost",
        "-c", "commit.gpgsign=false", "commit", "-m", "DMA smoke baseline", cwd=project)
    # Do not precreate .opc: init accepts only its own pre-contract layout.
    # Install these bindings after task/onboard and before the first loop.
    local = project / ".opc" / "local"
    bindings = {"workspace_root": str(destination / "workspaces"),
                "artifact_root": str(local / "artifacts")}
    (destination / "bindings.json").write_text(json.dumps(bindings, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1, "benchmark": "dma-backpressure", "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "framework_commit": git("rev-parse", "HEAD", cwd=REPO),
        "framework_dirty": bool(git("status", "--porcelain", "--untracked-files=normal", cwd=REPO)),
        "project_commit": git("rev-parse", "HEAD", cwd=project),
        "inputs_sha256": inputs,
        "examiner_sha256": hashlib.sha256((HERE / "examiner/acceptance.py").read_bytes()).hexdigest(),
        "python": sys.version, "bindings": bindings,
        "preparation_command": [sys.executable, str(Path(__file__).resolve()), str(destination)],
        "execution_commands": [], "model_configuration": None,
        "note": "Prepared only. Record actual skill/CLI commands, frozen contract and model configuration before running.",
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new run directory; existing paths are rejected")
    args = parser.parse_args()
    print(prepare(args.destination))
