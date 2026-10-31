"""Discussion handoff: validate before calling a worker, preserve exact input."""
import json
from pathlib import Path

import pytest

from opc.cli import main
from opc.core.model import OPCError
from opc.scaffold import init
from opc.scaffold.brief import SECTIONS, load_brief


FIELDS = {
    "Source": "Map: map.md\nStatus: ready-for-onboard\n输入复用；确认仅起草。",
    "Goal": "Goal: 说明输入在各阶段的复用位置\nDone when: 每个阶段都有带出处的复用结论\n"
            "Direction: 未定，先读源码",
    "Scope and deliverables": "In: 输入路径\nOut: 调度\n"
                              "- D1: 复用机制说明 | 机制说明 | 当前版本\n"
                              "- R1: 每条结论有源码出处 | verification=review | evaluator=未知\n"
                              "Objective: none: 机制说明没有数值指标",
}


def brief_project(tmp_path):
    (tmp_path / "map.md").write_text("# 自由结构地图\n研究输入复用与消费关系。\n", encoding="utf-8")
    body = "# 输入复用\n\n" + "\n\n".join(
        "## " + name + "\n" + FIELDS.get(name, "已记录：逐轮审核需要适配，阻塞执行；材料足够起草合同。")
        for name in SECTIONS)
    (tmp_path / "task-brief.md").write_text(body, encoding="utf-8")
    return body


def test_free_map_and_structural_scope(tmp_path):
    body = brief_project(tmp_path)
    result, loaded = load_brief(tmp_path, "task-brief.md")
    assert result["ok"] and loaded == body
    assert "not semantic" in result["check_scope"]
    assert main(["brief-check", "-p", str(tmp_path), "--brief", "task-brief.md"]) == 0
    (tmp_path / "map.md").write_text("# Another organization\n")
    assert load_brief(tmp_path, "task-brief.md")[0]["map_sha256"] != result["map_sha256"]


@pytest.mark.parametrize("old,new", [
    ("Status: ready-for-onboard", "Status: draft"),
    ("Map: map.md", "Map: missing.md"),
    ("Map: map.md", "Map: task-brief.md"),
    ("## Scope and deliverables", "## Removed"),
    ("## Scope and deliverables\n", "## Scope and deliverables\nTODO\n"),
    ("Map: map.md", "Map: map.md\nMap: map.md"),
    ("Goal: 说明", "目标: 说明"),
    ("Done when: ", "Done when:"),
    ("- D1: ", "D1 "),
    ("verification=review", "verification=maybe"),
    ("Objective: none", "objective none"),
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
    outside.write_text("# Outside")
    with pytest.raises(OPCError):
        load_brief(root, outside)
    try:
        (root / "link.md").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink privilege; direct outside path checked")
        raise
    (root / "task-brief.md").write_text(body.replace("Map: map.md", "Map: link.md"), encoding="utf-8")
    assert not load_brief(root, "task-brief.md")[0]["ok"]
    with pytest.raises(OPCError):
        load_brief(root, "link.md")



def test_cli_propagates_onboard_failure(monkeypatch):
    monkeypatch.setattr("opc.scaffold.onboard.onboard", lambda *a, **k: {"ok": False})
    assert main(["onboard", "-p", "."]) == 1
