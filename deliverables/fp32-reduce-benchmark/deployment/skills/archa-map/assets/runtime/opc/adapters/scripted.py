"""A deterministic worker: a search strategy instead of a model.

This is the "fixed search strategy + reliable evaluator" route of the OPC plan:
cheap, reproducible, and the baseline any model-driven expert has to beat per
unit of budget. The strategy is a frozen evaluator-side file:

    class Strategy:
        def __init__(self, options: dict): ...
        def propose(self, ctx: dict, tree: Path) -> dict | None  # plan, or None when exhausted
        def implement(self, plan: dict, tree: Path) -> None

`strategy: "builtin:param_search"` uses the bundled parameter search instead.
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any

from ..core.model import Cost, OPCError, write_json
from .worker import WorkerCall


class ScriptedWorker:
    def __init__(self, options: dict[str, Any], evaluator_tree: Path):
        ref = options.get("strategy")
        if ref == "builtin:param_search":
            from ..strategies.param_search import ParamSearch
            self.strategy = ParamSearch(dict(options.get("options") or {}))
            self.strategy.initial_config = json.loads(
                (evaluator_tree / self.strategy.file).read_text(encoding="utf-8"))
            return
        if not ref or ":" not in ref:
            raise OPCError("scripted worker needs strategy='path/file.py:Class' or "
                           "'builtin:param_search'")
        rel, cls = ref.rsplit(":", 1)
        path = evaluator_tree / rel
        spec = importlib.util.spec_from_file_location("opc_strategy", path)
        if spec is None or spec.loader is None or not path.exists():
            raise OPCError("cannot load strategy %s" % path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.strategy = getattr(module, cls)(dict(options.get("options") or {}))

    def propose(self, ctx: dict[str, Any], tree: Path, log_dir: Path) -> WorkerCall:
        t0 = time.time()
        try:
            plan = self.strategy.propose(ctx, tree)
        except Exception as exc:                     # noqa: BLE001 -- recorded as worker failure
            return WorkerCall("expert", False, Cost(time.time() - t0, 0, 0.0),
                              error="%s: %s" % (type(exc).__name__, exc))
        write_json(log_dir / "expert.json", {"plan": plan})
        cost = Cost(time.time() - t0, 0, 0.0)
        if plan is None:
            return WorkerCall("expert", True, cost, exhausted=True, log_dir=str(log_dir))
        return WorkerCall("expert", True, cost, call_id="scripted", output=plan,
                          log_dir=str(log_dir))

    def implement(self, plan: dict[str, Any], ctx: dict[str, Any], tree: Path,
                  log_dir: Path) -> WorkerCall:
        t0 = time.time()
        try:
            self.strategy.implement(plan, tree)
        except Exception as exc:                     # noqa: BLE001
            return WorkerCall("designer", False, Cost(time.time() - t0, 0, 0.0),
                              error="%s: %s" % (type(exc).__name__, exc))
        return WorkerCall("designer", True, Cost(time.time() - t0, 0, 0.0), call_id="scripted",
                          log_dir=str(log_dir))
