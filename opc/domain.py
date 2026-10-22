"""The seam between the core and a domain.

The core calls exactly these methods. Everything a domain knows (that a design
is RTL, that latency comes from an emulator log, which tool versions matter)
lives behind them. The default `CommandDomain` implements them from component
JSON alone; a project with needs beyond commands supplies its own class in a
frozen evaluator file and names it as `"adapter": "path/to/file.py:ClassName"`.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .core.config import ComponentConfig, matches
from .core.model import GateResult, OPCError, Outcome


@dataclass
class Evaluation:
    gates: list[GateResult]
    values: dict[str, float] = field(default_factory=dict)
    spread: dict[str, float] = field(default_factory=dict)
    repeats: int = 1
    degraded_by: list[str] = field(default_factory=list)
    failure: Outcome | None = None       # BROKEN or INFRA; None when every gate passed
    reason: str = ""
    seconds: float = 0.0


class DomainAdapter(Protocol):
    comp: ComponentConfig

    def toolchain(self) -> tuple[str, dict[str, str]]:
        """(digest, details) of the tools that turn a tree into numbers."""

    def evaluate(self, tree: Path, out_dir: Path, repeats: int) -> Evaluation:
        """Run the ordered gates on a clean tree; stop at the first failure."""

    def expert_context(self, tree: Path) -> dict[str, Any]:
        """Domain material the expert should see (sources, docs, extra hints)."""


def load_domain(comp: ComponentConfig, evaluator_tree: Path) -> DomainAdapter:
    """The adapter class is loaded from the frozen evaluator tree, never from a
    candidate tree, for the same reason the gates are."""
    if comp.adapter == "command":
        from .domains.command import CommandDomain
        return CommandDomain(comp)
    if ":" not in comp.adapter:
        raise OPCError("component adapter must be 'command' or 'path/file.py:Class'")
    rel, cls_name = comp.adapter.rsplit(":", 1)
    if not matches(rel, comp.evaluator_files + [".opc/**"]):
        raise OPCError("adapter file %s must be one of the frozen evaluator files" % rel)
    path = evaluator_tree / rel
    spec = importlib.util.spec_from_file_location("opc_domain_%s" % comp.component_id, path)
    if spec is None or spec.loader is None:
        raise OPCError("cannot load adapter %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, cls_name)(comp)

