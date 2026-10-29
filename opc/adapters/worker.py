"""The worker seam. Roles belong to OPC; a worker is only how a role gets executed.

An expert reads research material and results and returns a plan or stops exploration;
a designer locates and edits code. Acceptance and resource limits belong to the core.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..core.config import WorkerSpec
from ..core.model import Cost, OPCError

PLAN_FIELDS = ("title", "changes")

#: The one reply every model worker may give instead of a plan, meaning "no further
#: experiment is worth its budget". Shared so neither worker's termination depends
#: on the other's module staying present.
EXHAUSTED_SENTINEL = "NO_EXPERIMENT"

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [*PLAN_FIELDS, "hypothesis", "expected", "falsifier", "evaluate",
                 "exhausted", "base_attempt", "conclusions", "stop_reason", "experiment_id"],
    "properties": {
        "title": {"type": "string", "description": "short name of the experiment"},
        "hypothesis": {"type": "string", "description": "research question and competing explanations, or engineering rationale"},
        "experiment_id": {"type": ["string", "null"], "description": "stable question ID within this task, reused across runs; null for ordinary engineering work"},
        "changes": {"type": "string", "description": "method and experiment for the designer to implement"},
        "evaluate": {"type": ["boolean", "null"], "description": "formal evaluation: null uses objective-dependent default"},
        "base_attempt": {"type": ["integer", "null"],
                         "description": "null: champion; 0: initial baseline; positive: saved candidate attempt"},
        "conclusions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["attempt", "conclusion"], "properties": {
                "attempt": {"type": "integer"}, "conclusion": {"type": "string"}}}},
        "stop_reason": {"type": "string", "description": "why exploration should end; empty while continuing"},
        "expected": {"type": "string", "description": "distinguishing predictions under stated inputs and controls, not a mandatory result"},
        "falsifier": {"type": "string", "description": "observation that would refute it"},
        # codex's --output-schema admits only an object, so a worker with nothing
        # left to try has no way to say so in text. Strict structured output
        # requires every property: normal plans return false, exhausted ones true.
        "exhausted": {"type": "boolean",
                      "description": "true when no worthwhile work remains for the task within budget"},
    },
}


def request_rejected(message: str, executed: bool) -> bool:
    """Known provider request rejection, not a failure after useful execution."""
    markers = ("context_length_exceeded", "context window", "input too long", "prompt is too long",
               "maximum context length", "invalid_json_schema", "invalid schema for response_format",
               "invalid_request_error", "invalid request schema", "context length exceeded")
    return not executed and any(marker in message.lower() for marker in markers)


@dataclass
class WorkerCall:
    role: str
    ok: bool
    cost: Cost
    call_id: str = ""
    output: dict[str, Any] | None = None
    error: str = ""
    exhausted: bool = False            # the worker has no further experiment to propose
    log_dir: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Worker(Protocol):
    def propose(self, ctx: dict[str, Any], tree: Path, log_dir: Path) -> WorkerCall: ...

    def implement(self, plan: dict[str, Any], ctx: dict[str, Any], tree: Path,
                  log_dir: Path) -> WorkerCall: ...


def make_worker(spec: WorkerSpec, evaluator_tree: Path) -> Worker:
    if spec.kind == "codex":
        from .codex import CodexWorker
        return CodexWorker(spec.options)
    if spec.kind == "dsh":
        from .dsh import DshWorker
        return DshWorker(spec.options)
    if spec.kind == "scripted":
        from .scripted import ScriptedWorker
        return ScriptedWorker(spec.options, evaluator_tree)
    raise OPCError("unknown worker kind %r" % spec.kind)


def validate_plan(plan: Any) -> str | None:
    if not isinstance(plan, dict):
        return "plan is not an object"
    from ..core.results import validate_experiment_id
    from ..core.model import OPCError
    try:
        validate_experiment_id(plan.get("experiment_id"))
    except OPCError as exc:
        return str(exc)
    for k in PLAN_FIELDS:
        if not isinstance(plan.get(k), str) or not plan[k].strip():
            return "plan.%s is empty" % k
    files = plan.get("files")
    if files is not None and (not isinstance(files, list) or not all(
            isinstance(f, str) and f.strip() for f in files)):
        return "plan.files must be a list of paths when supplied"
    if plan.get("evaluate") is not None and type(plan["evaluate"]) is not bool:
        return "plan.evaluate must be boolean or null"
    base = plan.get("base_attempt")
    if base is not None and (type(base) is not int or base < 0):
        return "plan.base_attempt must be null or a nonnegative attempt number"
    return None
