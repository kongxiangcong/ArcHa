"""Plan OPC project paths or initialize draft metadata; never execute project code."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
RESERVED = {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"} | {
    f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)
}


def safe_id(value: str) -> str:
    if not ID_PATTERN.fullmatch(value) or value in RESERVED:
        raise ValueError(f"invalid portable identifier: {value!r}")
    return value


def inside(path: Path, parent: Path) -> bool:
    """Use case-insensitive comparisons for portable Windows-safe plans."""
    child_parts = tuple(p.casefold() for p in path.parts)
    parent_parts = tuple(p.casefold() for p in parent.parts)
    return child_parts[:len(parent_parts)] == parent_parts


def overlap(a: Path, b: Path) -> bool:
    return inside(a, b) or inside(b, a)


def project_directory(value: Path) -> Path:
    root = value.resolve()
    if not root.is_dir():
        raise ValueError("project root must be an existing directory")
    return root


def absolute_root(value: Path, label: str) -> Path:
    if not value.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    root = value.resolve()
    check_directory_chain(root, label)
    return root


def check_directory_chain(root: Path, label: str) -> None:
    if any(path.exists() and not path.is_dir() for path in (root, *root.parents)):
        raise ValueError(f"{label} contains a non-directory path")


def under(root: Path, *parts: str, directory: bool = False) -> Path:
    literal = root.joinpath(*parts)
    result = literal.resolve()
    if result != literal:
        raise ValueError("planned path is redirected or escapes its assigned root")
    if not inside(result, root):
        raise ValueError("resolved path escapes its assigned root")
    check_directory_chain(result if directory else result.parent, "planned directory")
    if not directory and result.exists() and not result.is_file():
        raise ValueError("planned file path is not a regular file")
    return result


def draft_files(project_id: str, name: str) -> dict[str, str]:
    safe_id(project_id)
    if not name.strip():
        raise ValueError("display name must not be empty")
    config = {
        "schema_version": "opc.project.v0.2",
        "project_id": project_id,
        "display_name": name,
        "protocol_version": "opc.v0.2",
        "control_root": ".opc",
        "components": ["default"],
        "adapter_id": "unconfigured",
        "artifact_store_alias": "artifacts",
        "workspace_store_alias": "workspaces",
        "baseline_policy": "clean_commit_or_explicit_snapshot",
        "execution_enabled": False,
    }
    return {
        "project.json": json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        ".gitignore": "# Machine bindings, ledger, artifacts and generated views\n/local/\n",
        "README.md": (
            "# OPC project draft\n\n"
            "This directory contains draft metadata only. Execution is disabled.\n\n"
            "Next: document requirements, define the default component and its editable/frozen paths, "
            "register tools/evaluator, bind local artifact and external workspace roots, "
            "select a clean commit or explicit snapshot, then run preflight.\n\n"
            "No source files, repository settings, Git state or runtime services were changed. "
            "Do not enable execution merely because these files exist.\n"
        ),
        "context/PROJECT.md": (
            f"# {name}\n\nProject ID: `{project_id}`\n\n"
            "## Goal and users\n\nTBD\n\n## Existing assets and constraints\n\nTBD\n\n"
            "## Out of scope\n\nTBD\n"
        ),
        "context/REQUIREMENTS.md": (
            "# Requirements draft\n\n"
            "| ID | Observable requirement | Source | Acceptance evidence | Status |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| req-001 | TBD | TBD | TBD | undecided |\n\n"
            "Requirements are not verified by the presence of an artifact alone.\n"
        ),
        "context/DECISIONS.md": (
            "# Decisions draft\n\n## Locked decisions and source\n\nTBD\n\n"
            "## Agent discretion within scope\n\nTBD\n\n"
            "## Deferred ideas and revisit conditions\n\nTBD\n"
        ),
        "components/README.md": (
            "# Components\n\n`default` is a reserved draft component ID, not an installed adapter. "
            "Create its validated component contract before dispatch. Explicitly identify editable "
            "paths, frozen reference/evaluator, tool argv, expected outputs, and resource constraints. "
            "This helper does not assume the project has src/, rtl/, tests/ or any particular language.\n"
        ),
        "tasks/README.md": (
            "# Task contracts\n\nUse `<task-id>/revisions/<revision>/` for immutable TaskSpec and "
            "supporting context. Runtime experiments belong in the artifact store, not here. "
            "Task execution and acceptance are owned by the control service, not Markdown status.\n"
        ),
    }


def initialize(project_root: Path, project_id: str, name: str, apply: bool = False) -> dict[str, Any]:
    root = project_directory(project_root)
    files = draft_files(project_id, name)
    # Also catches dangling symlinks and differently cased names on case-sensitive hosts.
    if any(entry.name.casefold() == ".opc" for entry in root.iterdir()):
        raise ValueError(".opc already exists; refusing to overwrite or merge it")
    control = root / ".opc"
    result = {"operation": "initialize_draft", "applied": apply, "project_root": str(root),
              "control_root": str(control), "files": sorted(files), "execution_enabled": False}
    if not apply:
        return result
    control.mkdir(exist_ok=False)
    for relative, content in files.items():
        target = under(control, *relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return result


def layout(project_root: Path, project_id: str, task_id: str, run_id: str, attempt: int,
           workspace_root: Path, artifact_root: Path | None = None,
           job_id: str = "job-000001", submission_id: str = "submission-000001",
           review_id: str = "review-000001") -> dict[str, Any]:
    root = project_directory(project_root)
    for value in (project_id, task_id, run_id, job_id, submission_id, review_id):
        safe_id(value)
    if type(attempt) is not int or not 1 <= attempt <= 999999:
        raise ValueError("attempt must be an integer between 1 and 999999")
    workspace = absolute_root(workspace_root, "workspace root")
    if overlap(workspace, root):
        raise ValueError("workspace root must be outside and disjoint from project root")
    local_artifacts = root / ".opc" / "local" / "artifacts"
    artifacts = absolute_root(artifact_root, "artifact root") if artifact_root else local_artifacts.resolve()
    check_directory_chain(artifacts, "artifact root")
    if inside(artifacts, root):
        if artifacts != local_artifacts or local_artifacts.resolve() != local_artifacts:
            raise ValueError("in-project artifact root must be .opc/local/artifacts without redirection")
    elif inside(root, artifacts):
        raise ValueError("artifact root may not contain the project")
    if artifact_root is None and local_artifacts.resolve() != local_artifacts:
        raise ValueError("default artifact root may not be redirected by a symlink")
    if overlap(artifacts, workspace):
        raise ValueError("artifact and workspace roots must be disjoint")
    attempt_id = f"a{attempt:06d}"
    run = under(artifacts, project_id, task_id, run_id, directory=True)
    trial = under(run, "attempts", attempt_id, directory=True)
    work = under(workspace, project_id, task_id, run_id, attempt_id, directory=True)
    paths = {
        "plan": under(trial, "plan.json"),
        "candidate_source": under(trial, "candidate", "source", directory=True),
        "job_stdout": under(trial, "experiment", "jobs", job_id, "stdout.txt"),
        "job_stderr": under(trial, "experiment", "jobs", job_id, "stderr.txt"),
        "job_receipt": under(trial, "experiment", "jobs", job_id, "receipt.json"),
        "submission_manifest": under(trial, "submissions", submission_id, "manifest.json"),
        "review_standards": under(trial, "reviews", review_id, "Standards.json"),
        "review_spec": under(trial, "reviews", review_id, "Spec.json"),
        "review_decision": under(trial, "reviews", review_id, "decision.json"),
        "designer_workspace": under(work, "designer", directory=True),
        "reviewer_workspace": under(work, "reviewer", directory=True),
    }
    normalized = [str(path).casefold() for path in paths.values()]
    if len(set(normalized)) != len(normalized):
        raise ValueError("planned paths collide")
    return {
        "project_id": project_id, "task_id": task_id, "run_id": run_id, "attempt_id": attempt_id,
        "artifact_root": str(artifacts), "workspace_root": str(workspace), "run_root": str(run),
        "attempt_root": str(trial), "paths": {key: str(value) for key, value in paths.items()},
        "artifact_uris": {key: "artifact://" + value.relative_to(artifacts).as_posix()
                          for key, value in paths.items() if inside(value, artifacts)},
        "note": "Path plan only; no directories, jobs or acceptance decisions are created.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="preview metadata; --apply creates a new .opc draft")
    init.add_argument("--project-root", type=Path, required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--apply", action="store_true")
    paths = sub.add_parser("paths", help="print artifact/workspace paths without writing")
    paths.add_argument("--project-root", type=Path, required=True)
    paths.add_argument("--project-id", required=True)
    paths.add_argument("--task-id", required=True)
    paths.add_argument("--run-id", required=True)
    paths.add_argument("--attempt", type=int, required=True)
    paths.add_argument("--workspace-root", type=Path, required=True)
    paths.add_argument("--artifact-root", type=Path)
    paths.add_argument("--job-id", default="job-000001")
    paths.add_argument("--submission-id", default="submission-000001")
    paths.add_argument("--review-id", default="review-000001")
    args = parser.parse_args()
    values = vars(args)
    command = values.pop("command")
    try:
        result = initialize(**values) if command == "init" else layout(**values)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
