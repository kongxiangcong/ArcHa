"""Structural checks for discussion handoffs, not scientific or execution approval."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..core.model import OPCError

SECTIONS = (
    "Source", "Question and use", "Goal", "Evidence", "Scope and deliverables", "Open decisions",
)
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME)\b|待填写|待补充", re.I)
# Fields onboard maps onto task.json: section, pattern, problem when absent.
FIELDS = (
    ("Goal", r"^Goal: \S", "Goal needs 'Goal: <one sentence>'"),
    ("Goal", r"^Done when: \S", "Goal needs 'Done when: <completion state>'"),
    ("Goal", r"^Direction: \S", "Goal needs 'Direction: <route or 未定>'"),
    ("Scope and deliverables", r"^- D\d+: \S", "Scope needs at least one '- D1: <deliverable>'"),
    ("Scope and deliverables", r"^- R\d+: .*\bverification=(?:automated|review)\b",
     "Scope needs at least one '- R1: <condition> | verification=automated|review'"),
    ("Scope and deliverables", r"^Objective: \S",
     "Scope needs 'Objective: <metric> minimize|maximize' or 'Objective: none: <reason>'"),
)


def load_brief(root: Path, brief: str | Path) -> tuple[dict, str]:
    root = root.resolve()
    path = Path(brief)
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        rel = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        body = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError, ValueError) as exc:
        raise OPCError("brief must be a readable UTF-8 file inside project: %s" % exc) from exc
    # Ignore fenced examples and comments when interpreting the handoff structure.
    visible = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    visible = re.sub(r"^```[^\n]*\n.*?^```\s*$", "", visible, flags=re.M | re.S)
    headings = list(re.finditer(r"^## ([^\n]+)\s*$", visible, re.M))
    sections = {}
    problems = []
    for i, heading in enumerate(headings):
        name = heading.group(1).strip()
        if name in sections:
            problems.append("duplicate section: " + name)
        sections[name] = visible[heading.end():headings[i + 1].start() if i + 1 < len(headings)
                                 else len(visible)].strip()
    for name in SECTIONS:
        if not sections.get(name):
            problems.append("missing or empty section: " + name)
        elif PLACEHOLDER.search(sections[name]):
            problems.append("unfilled placeholder in: " + name)
    for name, pattern, problem in FIELDS:
        if sections.get(name) and not re.search(pattern, sections[name], re.M):
            problems.append(problem)
    source = sections.get("Source", "")
    maps = re.findall(r"^Map: (.+)$", source, re.M)
    statuses = re.findall(r"^Status: (.+)$", source, re.M)
    map_rel = None
    map_digest = None
    if len(maps) != 1:
        problems.append("Source needs exactly one Map: <project-relative path>")
    else:
        try:
            source_path = Path(maps[0].strip())
            if source_path.is_absolute():
                raise ValueError("map path must be relative")
            map_path = (root / source_path).resolve()
            map_rel = map_path.relative_to(root).as_posix()
            if map_path == path:
                raise ValueError("map must differ from brief")
            map_raw = map_path.read_bytes()
            if not map_raw.decode("utf-8").strip():
                raise ValueError("map is empty")
            map_digest = hashlib.sha256(map_raw).hexdigest()
        except (OSError, UnicodeError, ValueError) as exc:
            problems.append("invalid source map: %s" % exc)
    if statuses != ["ready-for-onboard"]:
        problems.append("Source Status must be ready-for-onboard (drafts remain discussable)")
    return {
        "ok": not problems, "brief": rel, "sha256": hashlib.sha256(raw).hexdigest(),
        "map": map_rel, "map_sha256": map_digest, "problems": problems,
        "check_scope": "structure and source only; not semantic review or execution readiness",
    }, body
