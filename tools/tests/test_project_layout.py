from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.project_layout import initialize, layout


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preview_does_not_write_and_apply_preserves_sources(tmp_path: Path) -> None:
    project = tmp_path / "compiler"
    project.mkdir()
    source = project / "pipeline.py"
    source.write_text("def compile_graph(graph):\n    return graph\n", encoding="utf-8")
    before = source_hash(source)
    preview = initialize(project, "compiler-one", "Compiler")
    assert not preview["applied"]
    assert not (project / ".opc").exists()
    initialize(project, "compiler-one", "Compiler", apply=True)
    assert source_hash(source) == before
    assert sorted(p.name for p in project.iterdir()) == [".opc", "pipeline.py"]
    config = json.loads((project / ".opc/project.json").read_text(encoding="utf-8"))
    assert not config["execution_enabled"]
    assert config["adapter_id"] == "unconfigured"
    requirements = (project / ".opc/context/REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "| req-001 |" in requirements
    assert "REQ-001" not in requirements
    with pytest.raises(ValueError, match="already exists"):
        initialize(project, "compiler-one", "Compiler", apply=True)


@pytest.mark.parametrize("name", [".opc", ".OPC"])
def test_existing_control_file_is_never_overwritten(tmp_path: Path, name: str) -> None:
    original = tmp_path / name
    original.write_text("owned by user", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        initialize(tmp_path, "project", "Project", apply=True)
    assert original.read_text(encoding="utf-8") == "owned by user"


def test_projects_and_attempts_get_distinct_portable_paths(tmp_path: Path) -> None:
    project = tmp_path / "source"
    project.mkdir()
    artifacts = tmp_path / "artifacts"
    work = tmp_path / "work"
    one = layout(project, "p-one", "same-task", "same-run", 1, work, artifacts)
    two = layout(project, "p-two", "same-task", "same-run", 1, work, artifacts)
    attempt_two = layout(project, "p-one", "same-task", "same-run", 2, work, artifacts)
    assert one["paths"]["plan"] != two["paths"]["plan"]
    assert one["paths"]["plan"] != attempt_two["paths"]["plan"]
    assert one["artifact_uris"]["plan"] == "artifact://p-one/same-task/same-run/attempts/a000001/plan.json"
    assert not artifacts.exists() and not work.exists()


@pytest.mark.parametrize("unsafe", ["../escape", "a/b", "a\\b", "a:b", "CON", "con", "lpt1", "Project"])
def test_unsafe_identifiers_rejected_without_writes(tmp_path: Path, unsafe: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        initialize(tmp_path, unsafe, "Example", apply=True)
    assert not (tmp_path / ".opc").exists()


def test_nested_workspace_and_overlapping_artifact_root_rejected(tmp_path: Path) -> None:
    project = tmp_path / "source"
    project.mkdir()
    with pytest.raises(ValueError, match="outside"):
        layout(project, "project", "task", "run", 1, project / "work")
    with pytest.raises(ValueError, match="disjoint"):
        layout(project, "project", "task", "run", 1, tmp_path / "work", tmp_path / "work/artifacts")
    with pytest.raises(ValueError, match="in-project"):
        layout(project, "project", "task", "run", 1, tmp_path / "work", project / "src")
    with pytest.raises(ValueError, match="contain"):
        layout(project, "project", "task", "run", 1, tmp_path.parent / "outside-work", tmp_path)


def test_default_artifact_path_cannot_have_file_ancestor(tmp_path: Path) -> None:
    project = tmp_path / "source"
    project.mkdir()
    (project / ".opc").write_text("user file", encoding="utf-8")
    with pytest.raises(ValueError, match="non-directory"):
        layout(project, "project", "task", "run", 1, tmp_path / "work")


@pytest.mark.parametrize("conflict", ["candidate-parent", "candidate-leaf", "plan-file", "workspace-leaf"])
def test_generated_subpaths_reject_file_directory_conflicts(tmp_path: Path, conflict: str) -> None:
    project = tmp_path / "source"
    project.mkdir()
    artifacts = tmp_path / "artifacts"
    workspace = tmp_path / "work"
    attempt = artifacts / "project/task/run/attempts/a000001"
    if conflict == "candidate-parent":
        target = attempt / "candidate"
    elif conflict == "candidate-leaf":
        target = attempt / "candidate/source"
    elif conflict == "plan-file":
        target = attempt / "plan.json"
    else:
        target = workspace / "project/task/run/a000001/designer"
    target.parent.mkdir(parents=True, exist_ok=True)
    if conflict == "plan-file":
        target.mkdir()
    else:
        target.write_text("existing file must not become a directory", encoding="utf-8")
    with pytest.raises(ValueError, match="non-directory|not a regular file"):
        layout(project, "project", "task", "run", 1, workspace, artifacts)


def test_existing_candidate_symlink_cannot_escape_root(tmp_path: Path) -> None:
    project = tmp_path / "source"
    project.mkdir()
    artifacts = tmp_path / "artifacts"
    target = artifacts / "project/task/run/attempts/a000001"
    target.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (target / "candidate").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS disallows symlink creation")
    with pytest.raises(ValueError, match="escapes"):
        layout(project, "project", "task", "run", 1, tmp_path / "work", artifacts)
