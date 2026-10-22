"""Coordinate search over a JSON configuration file.

options:
    file      repository-relative JSON file to edit (must be editable)
    space     {"dotted.key": [candidate values in order], ...}
    order     optional list of keys, tried in this order (default: as given)
    steps     neighbours on each side of the current value (default 1)

Each proposal changes one key of the champion's configuration to a neighbouring
value. Configurations already tried (read from the history the engine passes in)
are skipped, so a rejected point is never re-run. When every neighbour of the
champion has been tried the strategy reports exhaustion: a local optimum on
this grid, which the engine records as `expert_exhausted`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get(d: dict, key: str) -> Any:
    for part in key.split("."):
        d = d[part]
    return d


def put(d: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


class ParamSearch:
    def __init__(self, options: dict[str, Any]):
        self.file = options["file"]
        self.space: dict[str, list] = options["space"]
        self.order = options.get("order") or list(self.space)
        self.steps = int(options.get("steps", 1))
        if not self.space:
            raise ValueError("param_search needs a non-empty space")

    def _current(self, tree: Path) -> dict:
        return json.loads((tree / self.file).read_text())

    def _point(self, cfg: dict) -> dict:
        return {k: get(cfg, k) for k in self.space}

    def propose(self, ctx: dict, tree: Path) -> dict | None:
        cfg = self._current(tree)
        point = self._point(cfg)
        tried_keys = {json.dumps(t, sort_keys=True) for t in ctx.get("tried_params") or []}
        focus = ctx.get("focus")
        keys = sorted(self.order, key=lambda k: 0 if focus and focus in k else 1)
        for step in range(1, self.steps + 1):
            for key in keys:
                values = self.space[key]
                cur = point[key]
                idx = values.index(cur) if cur in values else None
                neighbours = values if idx is None else \
                    [values[i] for i in (idx - step, idx + step) if 0 <= i < len(values)]
                for v in neighbours:
                    cand = dict(point)
                    cand[key] = v
                    if cand == point or json.dumps(cand, sort_keys=True) in tried_keys:
                        continue
                    return {"title": "%s: %s -> %s" % (key, cur, v),
                            "hypothesis": "moving %s from %s to %s improves %s" % (
                                key, cur, v, ctx["task"]["acceptance"]["objective"]["metric"]),
                            "files": [self.file],
                            "changes": "set %s = %s in %s" % (key, json.dumps(v), self.file),
                            "expected": "objective improves without violating constraints",
                            "falsifier": "objective does not clear the acceptance floor",
                            "params": cand}
        return None

    def implement(self, plan: dict, tree: Path) -> None:
        path = tree / self.file
        cfg = json.loads(path.read_text())
        for k, v in plan["params"].items():
            put(cfg, k, v)
        path.write_text(json.dumps(cfg, indent=2) + "\n")
