"""Runtime records shared by every domain.

Each type here exists because a real campaign (openTPU replayed under opc-TPU)
produced a wrong verdict without it; the docstrings name the failure.
"""
from __future__ import annotations

import enum
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class Outcome(str, enum.Enum):
    """What one attempt amounted to.

    INFRA and BROKEN are separate because openTPU recorded a congested host, a
    missing tool and a wrong candidate all as "broken": the same candidate went
    from broken to accepted by switching Verilator 5.053 to 5.046. INFRA does
    not consume search attempts.
    """

    IMPROVEMENT = "improvement"      # passed every gate and beat the champion
    NO_GAIN = "no_gain"              # passed every gate, did not beat the champion
    BROKEN = "broken"                # a gate failed because of the candidate
    SANDBOX = "sandbox_violation"    # touched a path outside its editable scope
    INFRA = "infra"                  # the host or a tool failed, not the candidate
    INCOMPARABLE = "incomparable"    # measured under another evaluator or toolchain
    NO_CHANGE = "no_change"          # the worker produced nothing to evaluate
    WORKER_FAILED = "worker_failed"  # expert/designer call failed or produced invalid output
    ABANDONED = "abandoned"          # controller stopped mid-attempt; costs kept, no verdict

    @property
    def counts_as_search(self) -> bool:
        return self not in (Outcome.INFRA, Outcome.ABANDONED)


class GateStatus(str, enum.Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"   # could not run; never the same as passed (openTPU's silent perf skip)
    INFRA = "infra"


@dataclass
class GateResult:
    gate_id: str
    status: GateStatus
    seconds: float
    exit_code: int | None = None
    detail: str = ""
    log_dir: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GateResult":
        return cls(gate_id=d["gate_id"], status=GateStatus(d["status"]), seconds=d["seconds"],
                   exit_code=d.get("exit_code"), detail=d.get("detail", ""),
                   log_dir=d.get("log_dir", ""))


@dataclass
class Measurements:
    """Numbers plus what produced them.

    On openTPU, Yosys 0.70 vs 0.69 moved area by 0.7% and fmax by up to 14.8%
    against a 1% acceptance threshold, and flipped a ranking. A number without
    its evaluator and toolchain digests cannot be compared with anything.
    """

    values: dict[str, float] = field(default_factory=dict)
    evaluator_digest: str = ""
    toolchain_digest: str = ""
    source_commit: str = ""
    spread: dict[str, float] = field(default_factory=dict)   # max-min over repeats
    repeats: int = 1
    degraded_by: list[str] = field(default_factory=list)     # gates that were skipped

    def comparable(self, other: "Measurements") -> tuple[bool, str]:
        for name in ("evaluator_digest", "toolchain_digest"):
            mine, theirs = getattr(self, name), getattr(other, name)
            if not mine or not theirs:
                return False, "%s missing" % name
            if mine != theirs:
                return False, "%s differs (%s vs %s)" % (name, theirs[:12], mine[:12])
        return True, ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Measurements | None":
        if not d:
            return None
        return cls(values={k: float(v) for k, v in (d.get("values") or {}).items()},
                   evaluator_digest=d.get("evaluator_digest", ""),
                   toolchain_digest=d.get("toolchain_digest", ""),
                   source_commit=d.get("source_commit", ""),
                   spread={k: float(v) for k, v in (d.get("spread") or {}).items()},
                   repeats=int(d.get("repeats") or 1),
                   degraded_by=list(d.get("degraded_by") or []))


@dataclass
class Verdict:
    accepted: bool
    reason: str
    gain: float = 0.0           # relative improvement of the objective, positive = better
    target_met: bool = False


@dataclass
class Cost:
    wall_seconds: float = 0.0
    tokens: int = 0
    usd: float | None = None    # None = unknown price; never silently 0 for a model call

    def add(self, other: "Cost") -> "Cost":
        usd = None if self.usd is None or other.usd is None else self.usd + other.usd
        return Cost(self.wall_seconds + other.wall_seconds, self.tokens + other.tokens, usd)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BudgetExhausted(RuntimeError):
    def __init__(self, kind: str, detail: str):
        super().__init__("%s: %s" % (kind, detail))
        self.kind = kind


class OPCError(RuntimeError):
    """A configuration or state problem the user must fix; never retried."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    """Atomic: a crash leaves the old file or the new one, never half of either."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
