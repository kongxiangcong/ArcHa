"""A domain defined entirely by component JSON: ordered commands plus a metrics file.

Gate exit-code convention (documented in the onboarding guide):

    0   passed
    75  infrastructure failure (EX_TEMPFAIL): host, license, tool, data unavailable
    77  skipped: the gate could not run (never counted as passed)
    *   failed because of the candidate

A timeout, or output matching an infra pattern, is also infrastructure.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

from ..core.platform import Process
from typing import Any

from ..core.config import ComponentConfig, GateSpec
from ..core.model import GateResult, GateStatus, Outcome, canonical_json, write_json
from ..domain import Evaluation, experimental_data

EX_TEMPFAIL = 75
TAIL = 4000


def run_command(argv: list[str], cwd: Path, env: dict[str, str], timeout: float,
                log_dir: Path) -> tuple[int | None, str, float, bool]:
    """(exit_code, tail, seconds, timed_out). The whole process group is killed on
    timeout so a simulator's children do not keep burning the host."""
    log_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(log_dir / "stdout.txt", "wb") as out, open(log_dir / "stderr.txt", "wb") as err:
        try:
            p = Process(argv, cwd=str(cwd), env=env, stdout=out, stderr=err)
        except OSError as exc:
            detail = "command could not start: %s" % exc
            (log_dir / "stderr.txt").write_text(detail + "\n", encoding="utf-8")
            return None, detail, time.time() - t0, False
        with p:
            try:
                code = p.wait(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                p.kill_tree()
                code, timed_out = None, True
    tail = ((log_dir / "stdout.txt").read_bytes()[-TAIL:] + b"\n" +
            (log_dir / "stderr.txt").read_bytes()[-TAIL:]).decode(errors="replace")
    return code, tail, time.time() - t0, timed_out


def read_metrics(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("metrics"), dict):
        data = data["metrics"]
    if not isinstance(data, dict):
        raise ValueError("metrics file must hold an object")
    out = {}
    for k, v in data.items():
        if isinstance(v, bool):
            out[k] = 1.0 if v else 0.0
        elif isinstance(v, (int, float)):
            out[k] = float(v)
    return out


class CommandDomain:
    def __init__(self, comp: ComponentConfig):
        self.comp = comp

    # ------------------------------------------------------------- toolchain
    def toolchain(self) -> tuple[str, dict[str, str]]:
        details = {"_host": canonical_json({"system": platform.system(),
                   "release": platform.release(), "machine": platform.machine(),
                   "python": platform.python_version()})}
        for argv in self.comp.toolchain:
            key = " ".join(argv)
            argv = [a.replace("{python}", sys.executable) for a in argv]
            try:
                with Process(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
                    stdout, stderr = p.communicate(timeout=60)
                details[key] = (stdout + stderr).decode("utf-8", errors="replace").strip()[:500] or "rc=%d" % p.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                details[key] = "unavailable: %s" % type(exc).__name__
        return hashlib.sha256(canonical_json(details).encode()).hexdigest(), details

    # -------------------------------------------------------------- evaluate
    def _env(self, gate: GateSpec, tree: Path, out: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.comp.env)
        env.update(gate.env)
        env.update({"OPC_WORKTREE": str(tree), "OPC_OUT": str(out),
                    "OPC_COMPONENT": self.comp.component_id})
        return env

    def _subst(self, s: str, tree: Path, out: Path) -> str:
        return (s.replace("{worktree}", str(tree)).replace("{out}", str(out))
                .replace("{python}", sys.executable))

    def _classify(self, code: int | None, tail: str, timed_out: bool) -> GateStatus:
        if timed_out:
            return GateStatus.INFRA
        if code == 0:
            return GateStatus.PASSED
        if code == self.comp.skip_exit_code:
            return GateStatus.SKIPPED
        if code is None or code in (EX_TEMPFAIL, 126, 127):
            return GateStatus.INFRA
        if any(p in tail for p in self.comp.infra_patterns):
            return GateStatus.INFRA
        return GateStatus.FAILED

    def evaluate(self, tree: Path, out_dir: Path, repeats: int, *,
                 diagnostic_gates: frozenset[str] = frozenset()) -> Evaluation:
        ev = Evaluation(gates=[], repeats=repeats)
        t_start = time.time()
        samples: dict[str, list[float]] = {}
        for gate in self.comp.gates:
            runs = repeats if gate.repeat and repeats > 1 else 1
            for r in range(runs):
                gid = gate.gate_id if runs == 1 else "%s#%d" % (gate.gate_id, r + 1)
                out = out_dir / gid
                out.mkdir(parents=True, exist_ok=True)
                argv = [self._subst(a, tree, out) for a in gate.argv]
                cwd = Path(self._subst(gate.cwd, tree, out))
                code, tail, secs, timed_out = run_command(argv, cwd, self._env(gate, tree, out),
                                                          gate.timeout_s, out)
                status = self._classify(code, tail, timed_out)
                detail = ("timeout after %ss" % gate.timeout_s) if timed_out else tail[-600:]
                if status is GateStatus.PASSED and gate.metrics:
                    mpath = Path(self._subst(gate.metrics, tree, out))
                    try:
                        ev.data.append({"gate": gate.gate_id, "repeat": r + 1,
                                        "data": experimental_data(
                                            json.loads(mpath.read_text(encoding="utf-8")))})
                        for k, v in read_metrics(mpath).items():
                            samples.setdefault(k, []).append(v)
                    except (OSError, ValueError) as exc:
                        # exit 0 without readable metrics is the evaluator's fault
                        status, detail = GateStatus.INFRA, "metrics unreadable: %s" % exc
                res = GateResult(gid, status, round(secs, 3), code, detail if status is not
                                 GateStatus.PASSED else "", str(out))
                write_json(out / "receipt.json", {"argv": argv, "cwd": str(cwd), **res.as_dict()})
                ev.gates.append(res)
                if status is GateStatus.SKIPPED:
                    ev.degraded_by.append(gate.gate_id)
                    if self.comp.on_skip == "reject":
                        ev.failure, ev.reason = Outcome.INFRA, "gate %s skipped" % gid
                    break               # a skipped gate is not repeated
                if status is GateStatus.INFRA:
                    ev.failure, ev.reason = Outcome.INFRA, "%s: %s" % (gid, detail[-300:])
                    break
                if status is GateStatus.FAILED:
                    if gate.gate_id not in diagnostic_gates:
                        ev.failure, ev.reason = Outcome.BROKEN, "%s: %s" % (gid, detail[-300:])
                    break
            if ev.failure is not None:
                break
        ev.seconds = time.time() - t_start
        if ev.failure is None:
            ev.values = {k: statistics.median(v) for k, v in samples.items()}
            ev.spread = {k: max(v) - min(v) for k, v in samples.items() if len(v) > 1}
        return ev

    # --------------------------------------------------------------- context
    def expert_context(self, tree: Path) -> dict[str, Any]:
        # Source context_files used to be injected into expert prompts. Research
        # notes are now selected by the core; implementation stays with designer.
        return {}
