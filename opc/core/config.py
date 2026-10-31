"""Load and validate the three contracts a project provides under `.opc/`.

    .opc/project.json                              ProjectConfig
    .opc/components/<component-id>.json            ComponentConfig
    .opc/tasks/<task-id>/revisions/<rev>/task.json TaskSpec

Validation is strict and fails closed: an acceptance rule that names no metric
would accept everything (openTPU's accept({}, {}) returned True), so it is a
configuration error, not a permissive default.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import OPCError, canonical_json
from .platform import portable_path

ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
REV = re.compile(r"r\d{4}\Z")
OPS = ("<", "<=", "==", ">=", ">", "!=")
DEFAULT_SCRATCH = ["**/__pycache__/**", "**/*.pyc", ".pytest_cache/**"]
DEFAULT_INFRA = [
    "Cannot allocate memory", "No space left on device", "command not found", "can't open file",
    "No such file or directory: '", "Connection refused", "Connection reset",
    "Temporary failure in name resolution", "Killed", "Resource temporarily unavailable",
]


def _need(d: dict, key: str, where: str, kind: type | tuple = object) -> Any:
    if key not in d:
        raise OPCError("%s: missing required field %r" % (where, key))
    if not isinstance(d[key], kind):
        raise OPCError("%s: field %r must be %s" % (where, key, getattr(kind, "__name__", kind)))
    return d[key]


def _keys(d: dict, allowed: set[str], where: str) -> None:
    """Unknown fields are errors, so a misspelled or foreign field never silently does nothing.
    Keys starting with `_` are free-form notes."""
    unknown = sorted(k for k in d if k not in allowed and not k.startswith("_"))
    if unknown:
        raise OPCError("%s: unknown field(s) %s; allowed: %s"
                       % (where, ", ".join(unknown), ", ".join(sorted(allowed))))


PROJECT_KEYS = {"project_id", "display_name", "components", "execution_enabled"}
COMPONENT_KEYS = {"component_id", "description", "editable", "frozen", "evaluator_files",
                  "scratch", "toolchain", "env", "gates", "infra_patterns", "skip_exit_code",
                  "on_skip", "context_files", "focus_areas", "adapter", "deterministic"}
GATE_KEYS = {"id", "argv", "timeout_s", "metrics", "repeat", "cwd", "env"}
TASK_KEYS = {"task_id", "revision", "component", "goal", "direction", "requirements",
             "acceptance", "budget", "workers", "base_ref", "preparation_review", "results_path"}
REQUIREMENT_KEYS = {"id", "text", "verification", "check", "gates", "required"}
ACCEPTANCE_KEYS = {"objective", "constraints", "target", "repeats", "noise_k", "rule",
                   "rule_params"}
OBJECTIVE_KEYS = {"metric", "direction", "min_rel_gain"}
CONSTRAINT_KEYS = {"metric", "op", "value", "relative_to_champion"}
BUDGET_KEYS = {"max_attempts", "max_wall_seconds", "max_tokens", "max_usd", "max_stagnation",
               "max_consecutive_infra"}


def _id(value: str, where: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value) or not portable_path(value):
        raise OPCError("%s: %r is not a portable id (lowercase, digits, '-')" % (where, value))
    return value


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise OPCError("missing %s" % path) from None
    except json.JSONDecodeError as exc:
        raise OPCError("%s is not valid JSON: %s" % (path, exc)) from None
    if not isinstance(data, dict):
        raise OPCError("%s must contain a JSON object" % path)
    return data


# ----------------------------------------------------------------------- globs
def glob_regex(pattern: str) -> re.Pattern:
    """`**` crosses directories, `*` and `?` do not; a trailing `/` means the subtree."""
    if pattern.endswith("/"):
        pattern += "**"
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


def denied(path: str, patterns: list[str]) -> bool:
    # Denials are case-insensitive on BOTH hosts. A contract cannot become weaker
    # when moved to a case-insensitive filesystem; grants remain exact-case.
    return matches(path.casefold(), [p.casefold() for p in patterns])


# -------------------------------------------------------------------- project
@dataclass
class ProjectConfig:
    root: Path
    project_id: str
    display_name: str
    components: list[str]
    execution_enabled: bool
    raw: dict

    @classmethod
    def load(cls, root: Path) -> "ProjectConfig":
        root = root.resolve()
        path = root / ".opc" / "project.json"
        d = _read(path)
        where = str(path)
        _keys(d, PROJECT_KEYS, where)
        return cls(root=root, project_id=_id(_need(d, "project_id", where, str), where),
                   display_name=d.get("display_name", ""),
                   components=list(d.get("components") or []),
                   execution_enabled=bool(d.get("execution_enabled", False)), raw=d)


# ------------------------------------------------------------------ component
@dataclass
class GateSpec:
    gate_id: str
    argv: list[str]
    timeout_s: int = 1800
    metrics: str | None = None          # path template of a JSON metrics file it writes
    repeat: bool = False                # re-run for noise estimation when acceptance.repeats > 1
    cwd: str = "{worktree}"
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class ComponentConfig:
    component_id: str
    description: str
    editable: list[str]
    frozen: list[str]
    evaluator_files: list[str]
    scratch: list[str]
    gates: list[GateSpec]
    toolchain: list[list[str]]
    env: dict[str, str]
    infra_patterns: list[str]
    skip_exit_code: int
    on_skip: str
    context_files: list[str]
    focus_areas: list[str]
    adapter: str                        # "command" or "package.module:Class"
    deterministic: bool                 # same tree + evaluator + toolchain => same numbers
    raw: dict
    path: Path

    @classmethod
    def load(cls, root: Path, component_id: str) -> "ComponentConfig":
        path = root / ".opc" / "components" / ("%s.json" % component_id)
        d = _read(path)
        where = str(path)
        _keys(d, COMPONENT_KEYS, where)
        cid = _id(_need(d, "component_id", where, str), where)
        if cid != component_id:
            raise OPCError("%s: component_id %r does not match file name" % (where, cid))
        editable = list(_need(d, "editable", where, list))
        if not editable:
            raise OPCError("%s: 'editable' is empty, so the sandbox would be vacuous" % where)
        frozen = list(d.get("frozen") or [])
        if ".opc/**" not in frozen:
            frozen.append(".opc/**")
        evaluator_files = list(_need(d, "evaluator_files", where, list))
        for p in editable + frozen + evaluator_files + list(d.get("scratch") or []):
            if not isinstance(p, str) or not portable_path(p):
                raise OPCError("%s: nonportable contract path %r" % (where, p))
        if not evaluator_files:
            raise OPCError("%s: 'evaluator_files' is empty; nothing pins what produces the "
                           "numbers" % where)
        for p in editable:
            if matches(p.rstrip("*").rstrip("/") or p, evaluator_files) or p.startswith(".opc"):
                raise OPCError("%s: editable path %r overlaps the evaluator" % (where, p))
            if not any(ch in p for ch in "*?") and not p.endswith("/") and matches(p, frozen):
                raise OPCError("%s: editable path %r is also frozen, so nothing could ever be "
                               "edited (deny wins); frozen only carves exceptions out of "
                               "editable globs" % (where, p))
        gates = []
        for i, g in enumerate(_need(d, "gates", where, list)):
            gw = "%s gates[%d]" % (where, i)
            _keys(g, GATE_KEYS, gw)
            gid = _id(_need(g, "id", gw, str), gw)
            argv = _need(g, "argv", gw, list)
            if not argv or not all(isinstance(a, str) for a in argv):
                raise OPCError("%s: argv must be a non-empty list of strings" % gw)
            if argv[0] in ("sh", "bash", "/bin/sh", "/bin/bash") and "-c" in argv[1:2]:
                raise OPCError("%s: 'sh -c' hides the real command; put it in a script under "
                               "the evaluator files instead" % gw)
            program = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
            if ((program in ("cmd", "cmd.exe") and any(a.lower() in ("/c", "/k") for a in argv[1:]))
                    or (program in ("powershell", "powershell.exe", "pwsh", "pwsh.exe")
                        and any(a.lower() in ("-c", "-command", "-encodedcommand", "-enc") for a in argv[1:]))):
                raise OPCError("%s: inline shell commands hide the evaluator; use a frozen script" % gw)
            gates.append(GateSpec(gate_id=gid, argv=argv, timeout_s=int(g.get("timeout_s", 1800)),
                                  metrics=g.get("metrics"), repeat=bool(g.get("repeat", False)),
                                  cwd=g.get("cwd", "{worktree}"), env=dict(g.get("env") or {})))
        if not gates:
            raise OPCError("%s: no gates" % where)
        if len({g.gate_id for g in gates}) != len(gates):
            raise OPCError("%s: duplicate gate ids" % where)
        on_skip = d.get("on_skip", "reject")
        if on_skip not in ("reject", "degrade"):
            raise OPCError("%s: on_skip must be 'reject' or 'degrade'" % where)
        return cls(component_id=cid, description=d.get("description", ""), editable=editable,
                   frozen=frozen, evaluator_files=evaluator_files,
                   scratch=list(d.get("scratch") or []) + DEFAULT_SCRATCH, gates=gates,
                   toolchain=[list(c) for c in d.get("toolchain") or []],
                   env={str(k): str(v) for k, v in (d.get("env") or {}).items()},
                   infra_patterns=list(d.get("infra_patterns") or []) + DEFAULT_INFRA,
                   skip_exit_code=int(d.get("skip_exit_code", 77)), on_skip=on_skip,
                   context_files=list(d.get("context_files") or []),
                   focus_areas=list(d.get("focus_areas") or []),
                   adapter=d.get("adapter", "command"),
                   deterministic=bool(d.get("deterministic", False)), raw=d, path=path)

    def is_editable(self, path: str) -> bool:
        """Deny wins: a glob that reaches into a frozen or evaluator path is refused."""
        if not portable_path(path) or denied(path, self.frozen + self.evaluator_files):
            return False
        return matches(path, self.editable)

    def is_scratch(self, path: str) -> bool:
        return (portable_path(path) and not denied(path, self.frozen + self.evaluator_files)
                and matches(path, self.scratch))


# ----------------------------------------------------------------------- task
@dataclass
class Constraint:
    metric: str
    op: str
    value: float | None = None
    relative_to_champion: float | None = None   # bound = champion * factor

    def describe(self) -> str:
        if self.relative_to_champion is not None:
            return "%s %s champion*%g" % (self.metric, self.op, self.relative_to_champion)
        return "%s %s %g" % (self.metric, self.op, self.value)


@dataclass
class Acceptance:
    objective_metric: str | None
    direction: str                       # minimize | maximize
    min_rel_gain: float
    constraints: list[Constraint]
    target: Constraint | None
    repeats: int
    noise_k: float
    rule: str | None                     # "path/in/evaluator.py:function" (frozen evaluator file)
    rule_params: dict[str, Any]


@dataclass
class WorkerSpec:
    kind: str                            # codex | scripted
    options: dict[str, Any]


@dataclass
class Budget:
    max_attempts: int | None
    max_wall_seconds: float | None
    max_tokens: int | None
    max_usd: float | None
    max_stagnation: int
    max_consecutive_infra: int


@dataclass
class TaskSpec:
    task_id: str
    revision: str
    component: str
    goal: str
    direction: str
    requirements: list[dict]
    acceptance: Acceptance
    budget: Budget
    expert: WorkerSpec
    designer: WorkerSpec | None
    base_ref: str
    digest: str
    path: Path
    raw: dict

    @classmethod
    def save_revision(cls, root: Path, task_id: str, revision: str, values: dict) -> "TaskSpec":
        """Save an authorized candidate edit; executed contracts receive a new identity."""
        from .model import write_json
        root = root.resolve()
        _id(task_id, "task_id")
        if not REV.fullmatch(revision):
            raise OPCError("revision must be rNNNN")
        if values.get("task_id") != task_id:
            raise OPCError("saved contract task_id does not match the selected Task")
        values = {**values, "revision": revision}
        tdir = root / ".opc/tasks" / task_id / "revisions"
        frozen = cls.frozen_digest(root, task_id, revision)
        if frozen is not None and hashlib.sha256(canonical_json(values).encode()).hexdigest() != frozen:
            numbers = [int(p.name[1:]) for p in tdir.iterdir() if REV.fullmatch(p.name)]
            number = max(numbers, default=0) + 1
            if number > 9999:
                raise OPCError("task revision numbers exhausted")
            revision = "r%04d" % number
            values = {**values, "revision": revision}
        write_json(tdir / revision / "task.json", values)
        return cls.load(root, task_id, revision)

    @classmethod
    def frozen_digest(cls, root: Path, task_id: str, revision: str) -> str | None:
        """Identity of the source contract first bound to execution, including legacy Runs."""
        from .ledger import Ledger
        from .workspace import git
        path = root / ".opc/local/ledger.sqlite3"
        if not path.is_file():
            return None
        runs = [r for r in Ledger(path).runs()
                if r["task_id"] == task_id and r["revision"] == revision]
        if not runs:
            return None
        run = runs[0]
        contract = f".opc/tasks/{task_id}/revisions/{revision}/task.json"
        project = ProjectConfig.load(root)
        bindings = Bindings.load(project)
        snapshot = bindings.artifact_root / project.project_id / task_id / run["run_id"] / "frozen/baseline.json"
        if snapshot.is_file():
            frozen = _read(snapshot)
            if frozen.get("source_contract_digest"):
                return frozen["source_contract_digest"]
        try:
            source = json.loads(git("show", run["base_commit"] + ":" + contract, cwd=root))
        except (OPCError, ValueError) as exc:
            raise OPCError("frozen revision %s source is unavailable: %s" % (revision, exc)) from exc
        return hashlib.sha256(canonical_json(source).encode()).hexdigest()

    @classmethod
    def load(cls, root: Path, task_id: str, revision: str | None = None) -> "TaskSpec":
        tdir = root / ".opc" / "tasks" / task_id / "revisions"
        if revision is None:
            revs = sorted(p.name for p in tdir.glob("r[0-9][0-9][0-9][0-9]") if p.is_dir())
            if not revs:
                raise OPCError("task %r has no revisions under %s" % (task_id, tdir))
            revision = revs[-1]
        path = tdir / revision / "task.json"
        d = _read(path)
        where = str(path)
        _keys(d, TASK_KEYS, where)
        if d.get("results_path") is not None:
            from .results import entry_path
            entry_path(root, d["results_path"])
        if "preparation_review" in d and type(d["preparation_review"]) is not bool:
            raise OPCError("preparation_review must be boolean")
        for i, r in enumerate(d.get("requirements") or []):
            _keys(r, REQUIREMENT_KEYS, "%s requirements[%d]" % (where, i))
            if "required" in r and type(r["required"]) is not bool:
                raise OPCError("requirement.required must be boolean")
            if "gates" in r and (not isinstance(r["gates"], list) or not r["gates"] or
                                  not all(isinstance(g, str) and g for g in r["gates"])):
                raise OPCError("requirement.gates must name nonempty gate IDs")
        if _id(_need(d, "task_id", where, str), where) != task_id:
            raise OPCError("%s: task_id does not match its directory" % where)
        if _need(d, "revision", where, str) != revision or not REV.fullmatch(revision):
            raise OPCError("%s: revision must equal its directory name rNNNN" % where)
        acc = _need(d, "acceptance", where, dict)
        aw = where + " acceptance"
        _keys(acc, ACCEPTANCE_KEYS, aw)
        obj = acc.get("objective")
        if obj is not None and not isinstance(obj, dict):
            raise OPCError("objective must be an object or null")
        obj = obj if obj is not None else {}
        _keys(obj, OBJECTIVE_KEYS, aw + ".objective")
        direction = _need(obj, "direction", aw + ".objective", str) if obj else ""
        if obj and direction not in ("minimize", "maximize"):
            raise OPCError("%s.objective.direction must be minimize or maximize" % aw)

        def constraint(c: dict, w: str) -> Constraint:
            _keys(c, CONSTRAINT_KEYS, w)
            op = _need(c, "op", w, str)
            if op not in OPS:
                raise OPCError("%s: op must be one of %s" % (w, OPS))
            if ("value" in c) == ("relative_to_champion" in c):
                raise OPCError("%s: give exactly one of value / relative_to_champion" % w)
            return Constraint(metric=_need(c, "metric", w, str), op=op,
                              value=float(c["value"]) if "value" in c else None,
                              relative_to_champion=(float(c["relative_to_champion"])
                                                    if "relative_to_champion" in c else None))

        target = acc.get("target")
        acceptance = Acceptance(
            objective_metric=_need(obj, "metric", aw + ".objective", str) if obj else None, direction=direction,
            min_rel_gain=float(obj.get("min_rel_gain", 0.0)),
            constraints=[constraint(c, "%s.constraints[%d]" % (aw, i))
                         for i, c in enumerate(acc.get("constraints") or [])],
            target=constraint(target, aw + ".target") if target else None,
            repeats=max(1, int(acc.get("repeats", 1))), noise_k=float(acc.get("noise_k", 2.0)),
            rule=acc.get("rule"), rule_params=dict(acc.get("rule_params") or {}))
        if acceptance.target and acceptance.target.relative_to_champion is not None:
            raise OPCError("%s.target must be an absolute value" % aw)

        if not acceptance.objective_metric and (acceptance.rule or any(
                c.relative_to_champion is not None for c in acceptance.constraints)):
            raise OPCError("relative constraints and ranking rule require an objective")

        b = _need(d, "budget", where, dict)
        bw = where + " budget"
        _keys(b, BUDGET_KEYS, bw)
        from .worker_config import load_budget_config, resolve_budget_limits
        local_limits = load_budget_config(root)
        caps = resolve_budget_limits(b, local_limits)
        budget = Budget(max_attempts=b.get("max_attempts"),
                        max_wall_seconds=caps.get("max_wall_seconds"),
                        max_tokens=caps.get("max_tokens"), max_usd=b.get("max_usd"),
                        max_stagnation=int(b.get("max_stagnation", 8)),
                        max_consecutive_infra=int(b.get("max_consecutive_infra", 3)))
        if budget.max_attempts is not None and (type(budget.max_attempts) is not int or budget.max_attempts < 1):
            raise OPCError("%s: max_attempts must be positive" % bw)

        w = _need(d, "workers", where, dict)

        def worker(spec: dict | None, role: str) -> WorkerSpec | None:
            if spec is None:
                return None
            kind = _need(spec, "kind", "%s workers.%s" % (where, role), str)
            if kind not in ("codex", "dsh", "scripted"):
                raise OPCError("%s workers.%s.kind must be codex, dsh or scripted"
                               % (where, role))
            return WorkerSpec(kind=kind, options={k: v for k, v in spec.items() if k != "kind"})

        expert = worker(_need(w, "expert", where + " workers", dict), "expert")
        designer = worker(w.get("designer"), "designer")
        # Model workers need a designer; resource caps are optional user settings.
        model_kinds = ("codex", "dsh")
        if expert.kind in model_kinds and designer is None:
            raise OPCError("%s: a %s expert needs a designer worker" % (where, expert.kind))
        if local_limits:
            d = {**d, "budget": {**b, **caps}}
        digest = hashlib.sha256(canonical_json(d).encode()).hexdigest()
        return cls(task_id=task_id, revision=revision, component=_id(_need(d, "component", where,
                                                                         str), where),
                   goal=_need(d, "goal", where, str), direction=d.get("direction", ""),
                   requirements=list(d.get("requirements") or []), acceptance=acceptance,
                   budget=budget, expert=expert, designer=designer,
                   base_ref=d.get("base_ref", "HEAD"), digest=digest, path=path, raw=d)


# ------------------------------------------------------------------- bindings
@dataclass
class Bindings:
    workspace_root: Path
    artifact_root: Path

    @classmethod
    def load(cls, project: ProjectConfig) -> "Bindings":
        local = project.root / ".opc" / "local"
        path = local / "bindings.json"
        d = _read(path) if path.exists() else {}
        ws = Path(d.get("workspace_root") or
                  project.root.parent / ".opc-workspaces" / project.project_id).resolve()
        art = Path(d.get("artifact_root") or local / "artifacts").resolve()
        root = project.root
        if ws == root or root in ws.parents or ws in root.parents:
            raise OPCError("workspace_root %s must be outside and disjoint from the project" % ws)
        if art == ws or ws in art.parents or art in ws.parents:
            raise OPCError("artifact_root and workspace_root must be disjoint")
        return cls(workspace_root=ws, artifact_root=art)
