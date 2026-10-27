"""Discussion handoff: validate before calling a worker, preserve exact input."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opc.cli import main
from opc.core.model import OPCError
from opc.scaffold import init
from opc.scaffold.brief import SECTIONS, load_brief
from opc.scaffold.onboard import _draft as onboard


def brief_project(tmp_path):
    (tmp_path / "map.md").write_text("# 自由结构地图\n研究输入复用与消费关系。\n", encoding="utf-8")
    body = "# 输入复用\n\n" + "\n\n".join(
        "## " + name + "\n" + (
            "Map: map.md\nStatus: ready-for-onboard\nDirection: 输入复用；确认仅起草。"
            if name == "Source" else
            "Goal: 验证输入复用\nDone when: 完成验证\nDirection: 输入复用"
            if name == "Goal" else
            "- D1: 验证报告\n- R1: 报告完成 | verification=review\nObjective: 无数值目标"
            if name == "Scope and deliverables" else
            "已记录：逐轮审核需要适配，阻塞执行；材料足够起草合同。"
        ) for name in SECTIONS)
    (tmp_path / "task-brief.md").write_text(body, encoding="utf-8")
    return body


def test_free_map_and_structural_scope(tmp_path):
    body = brief_project(tmp_path)
    result, loaded = load_brief(tmp_path, "task-brief.md")
    assert result["ok"] and loaded == body
    assert "not semantic" in result["check_scope"]
    assert main(["brief-check", "-p", str(tmp_path), "--brief", "task-brief.md"]) == 0
    (tmp_path / "map.md").write_text("# Another organization\n", encoding="utf-8")
    assert load_brief(tmp_path, "task-brief.md")[0]["map_sha256"] != result["map_sha256"]


@pytest.mark.parametrize("old,new", [
    ("Status: ready-for-onboard", "Status: draft"),
    ("Map: map.md", "Map: missing.md"),
    ("Map: map.md", "Map: task-brief.md"),
    ("## Scope and deliverables", "## Removed"),
    ("## Scope and deliverables\n", "## Scope and deliverables\nTODO\n"),
    ("Map: map.md", "Map: map.md\nMap: map.md"),
])
def test_incomplete_briefs_fail(tmp_path, old, new):
    body = brief_project(tmp_path)
    (tmp_path / "task-brief.md").write_text(body.replace(old, new), encoding="utf-8")
    assert not load_brief(tmp_path, "task-brief.md")[0]["ok"]
    assert main(["brief-check", "-p", str(tmp_path), "--brief", "task-brief.md"]) == 1


def test_outside_source_and_brief_rejected(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    body = brief_project(root)
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside", encoding="utf-8")
    try:
        (root / "link.md").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable; junctions tested separately")
        raise
    (root / "task-brief.md").write_text(body.replace("Map: map.md", "Map: link.md"), encoding="utf-8")
    assert not load_brief(root, "task-brief.md")[0]["ok"]
    with pytest.raises(OPCError):
        load_brief(root, "link.md")


def test_onboard_consumes_and_records_brief(tmp_path, monkeypatch):
    body = brief_project(tmp_path)
    init(tmp_path, "demo", "Demo", "main", "t-main", True)
    monkeypatch.setattr("opc.scaffold.onboard._snapshot", lambda root: {})
    calls = []

    def run(self, role, prompt, tree, log, sandbox, schema):
        calls.append(prompt)
        assert body in prompt
        assert "context_files" in prompt and "blocking Open" in prompt
        return SimpleNamespace(ok=True, call_id="fake", cost=SimpleNamespace(tokens=4), error=""), "drafted"

    monkeypatch.setattr("opc.adapters.codex.CodexWorker._run", run)
    result = onboard(tmp_path, "codex", "task-brief.md")
    assert result["ok"] and result["brief_input"]["map"] == "map.md"
    assert (tmp_path / ".opc/local/onboard/task-brief.md").read_text(encoding="utf-8") == body
    metadata = json.loads((tmp_path / ".opc/local/onboard/brief-input.json").read_text(encoding="utf-8"))
    assert metadata["sha256"] == result["brief_input"]["sha256"]
    (tmp_path / "task-brief.md").write_text(body.replace("ready-for-onboard", "draft"), encoding="utf-8")
    with pytest.raises(OPCError, match="not ready"):
        onboard(tmp_path, "codex", "task-brief.md")
    assert len(calls) == 1


def test_cli_propagates_onboard_failure(monkeypatch):
    monkeypatch.setattr("opc.scaffold.onboard.onboard", lambda *a, **k: {"ok": False})
    assert main(["onboard", "-p", "."]) == 1


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_onboard_rejects_rewriting_research_inputs(tmp_path, monkeypatch, action):
    init(tmp_path, "demo", "Demo", "main", "t-main", True)
    research = tmp_path / ".opc/research"
    research.mkdir()
    source = research / "evidence.md"
    source.write_text("original evidence", encoding="utf-8")
    # Input protection must work even when git dirty-path reporting omits these files.
    monkeypatch.setattr("opc.scaffold.onboard._snapshot", lambda root: {})

    def run(*args):
        if action == "edit":
            source.write_text("changed evidence", encoding="utf-8")
        else:
            source.unlink()
        return SimpleNamespace(ok=True, call_id="fake", cost=SimpleNamespace(tokens=0), error=""), "done"

    monkeypatch.setattr("opc.adapters.codex.CodexWorker._run", run)
    result = onboard(tmp_path, "codex")
    assert not result["ok"]
    assert result["changed_protected_opc"] == [".opc/research/evidence.md"]


def test_direct_task_source_without_map(tmp_path):
    body = brief_project(tmp_path)
    (tmp_path / 'TASK.md').write_text('Confirmed engineering requirements', encoding='utf-8')
    (tmp_path / 'task-brief.md').write_text(body.replace('Map: map.md', 'Task: TASK.md'), encoding='utf-8')
    report, _ = load_brief(tmp_path, 'task-brief.md')
    assert report['ok'] and report['map'] is None and report['task_source'] == 'TASK.md'
    (tmp_path / 'TASK.md').unlink()
    assert not load_brief(tmp_path, 'task-brief.md')[0]['ok']
