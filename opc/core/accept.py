"""Deterministic acceptance: constraints, objective gain above noise, optional frozen rule.

Fails closed. A metric the rule names but the evaluation did not produce is a
rejection, not a pass: openTPU's accept() with empty metrics returned True.
"""
from __future__ import annotations

import importlib.util
import math
import operator
from pathlib import Path
from typing import Callable

from .config import Acceptance, Constraint, matches
from .model import Measurements, OPCError, Verdict

OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt, "<=": operator.le, "==": lambda a, b: math.isclose(a, b, rel_tol=1e-12),
    ">=": operator.ge, ">": operator.gt, "!=": lambda a, b: not math.isclose(a, b, rel_tol=1e-12),
}


def required_metrics(acc: Acceptance) -> list[str]:
    names = ([acc.objective_metric] if acc.objective_metric else []) + [c.metric for c in acc.constraints]
    if acc.target:
        names.append(acc.target.metric)
    return sorted(set(names))


def check(c: Constraint, values: dict[str, float], champion: dict[str, float] | None) -> str | None:
    """None when satisfied, otherwise the reason."""
    if c.metric not in values:
        return "metric %s missing" % c.metric
    if c.relative_to_champion is not None:
        if champion is None or c.metric not in champion:
            return "champion has no %s to bound against" % c.metric
        bound = champion[c.metric] * c.relative_to_champion
    else:
        bound = c.value
    if not OPS[c.op](values[c.metric], bound):
        return "%s=%g violates %s (bound %g)" % (c.metric, values[c.metric], c.describe(), bound)
    return None


def relative_gain(acc: Acceptance, old: float, new: float) -> float:
    """Positive = better, relative to |old|."""
    if old == 0:
        return math.inf if (new < old if acc.direction == "minimize" else new > old) else 0.0
    delta = (old - new) if acc.direction == "minimize" else (new - old)
    return delta / abs(old)


def target_met(acc: Acceptance, values: dict[str, float]) -> bool:
    return acc.target is not None and check(acc.target, values, None) is None


def load_rule(acc: Acceptance, evaluator_tree: Path, evaluator_files: list[str]):
    """A custom rule is code that judges, so it must be a frozen evaluator file and
    is loaded from the evaluator tree (same-source: the rule that judges a tree
    comes from the commit that tree was cut from)."""
    if not acc.rule:
        return None
    rel, fn = acc.rule.rsplit(":", 1)
    if not matches(rel, evaluator_files):
        raise OPCError("acceptance.rule %s is not covered by evaluator_files" % rel)
    spec = importlib.util.spec_from_file_location("opc_rule", evaluator_tree / rel)
    if spec is None or spec.loader is None:
        raise OPCError("cannot load acceptance rule %s" % rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, fn)


def judge(acc: Acceptance, champion: Measurements, cand: Measurements, rule=None) -> Verdict:
    missing = [m for m in required_metrics(acc) if m not in cand.values]
    if missing:
        return Verdict(False, "candidate did not report %s" % ", ".join(missing))
    for c in acc.constraints:
        why = check(c, cand.values, champion.values)
        if why:
            return Verdict(False, "constraint: " + why)
    m = acc.objective_metric
    if m not in champion.values:
        return Verdict(False, "champion has no %s" % m)
    gain = relative_gain(acc, champion.values[m], cand.values[m])
    met = target_met(acc, cand.values)
    if rule is not None:
        ok, why = rule(dict(champion.values), dict(cand.values), **acc.rule_params)
        return Verdict(bool(ok), "rule: %s" % why, gain, met and bool(ok))
    # noise floor: with repeats, a gain inside the measured spread is not a gain
    noise = 0.0
    if champion.values[m]:
        spread = max(champion.spread.get(m, 0.0), cand.spread.get(m, 0.0))
        noise = acc.noise_k * spread / abs(champion.values[m])
    floor = max(acc.min_rel_gain, noise)
    if gain > floor:
        return Verdict(True, "%s %+.2f%% (floor %.2f%%)" % (m, 100 * gain, 100 * floor), gain, met)
    return Verdict(False, "%s %+.2f%% does not clear floor %.2f%%%s"
                   % (m, 100 * gain, 100 * floor, " (noise)" if noise > acc.min_rel_gain else ""),
                   gain, False)
