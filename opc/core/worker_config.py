"""Machine-local model settings and optional resource caps."""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .model import OPCError
from .platform import command_prefix

ROLES = ("expert", "designer", "reviewer", "onboard")
CONFIG_PATH = ".opc/local/workers.json"
FIELDS = {"kind", "binary", "model", "reasoning_effort", "provider", "codex_home", "dsh_home", "profile"}


def _load_config(root: Path) -> dict[str, Any]:
    path = root / CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise OPCError("cannot read %s: %s" % (path, exc)) from exc
    if not isinstance(data, dict) or set(data) - set(ROLES) - {"budget"}:
        raise OPCError("%s: expected budget and role objects: %s" % (path, ", ".join(ROLES)))
    validate_limits(data.get("budget", {}))
    return data


def load_worker_config(root: Path) -> dict[str, dict[str, Any]]:
    path = root / CONFIG_PATH
    data = _load_config(root)
    result = {}
    for role, values in data.items():
        if role == "budget":
            continue
        if not isinstance(values, dict) or set(values) - FIELDS:
            raise OPCError("%s: %s allows only %s" % (path, role, ", ".join(sorted(FIELDS))))
        result[role] = {}
        for key, value in values.items():
            if value is None:
                continue
            if key == "binary" and isinstance(value, list):
                try:
                    command_prefix(value)
                except ValueError as exc:
                    raise OPCError("%s: %s.binary: %s" % (path, role, exc)) from exc
                result[role][key] = value
                continue
            if not isinstance(value, str) or not value.strip():
                raise OPCError("%s: %s.%s must be a nonempty string or null" % (path, role, key))
            result[role][key] = value
    return result


def resolve_worker(config: dict, role: str, base=None, *, restricted: bool = False,
                   default_kind: str = "codex", sources: dict | None = None):
    """Resolve one role once; callers persist this spec instead of rereading defaults."""
    from .config import WorkerSpec
    local = config.get(role, {})
    kind = local.get("kind", base.kind if base else default_kind)
    if kind not in ("codex", "dsh", "scripted"):
        raise OPCError("%s backend must be codex, dsh or scripted" % role)
    if restricted and base and kind != base.kind:
        raise OPCError("%s backend conflict: contract requires %s, environment selects %s" % (role, base.kind, kind))
    # A backend change cannot inherit another backend's model, provider or flags.
    options = dict(base.options) if base and base.kind == kind else {}
    options.update({k: v for k, v in local.items() if k != "kind"})
    if sources is not None:
        if base and base.kind != kind:
            for key in list(sources):
                if key.startswith("workers.%s." % role):
                    del sources[key]
        for key in local:
            sources["workers.%s.%s" % (role, key)] = CONFIG_PATH
        sources.setdefault("workers.%s.kind" % role, "backend default")
    if kind != "scripted":
        prefix = "OPC_" + kind.upper()
        binary = options.get("binary") or os.environ.get(prefix + "_BIN")
        if not binary:
            binary = ((shutil.which("codex.exe") if sys.platform == "win32" else None)
                      or kind)
        prefix_argv = command_prefix(binary)
        located = shutil.which(str(Path(prefix_argv[0]).expanduser()))
        if located:
            prefix_argv[0] = str(Path(located).resolve())
        else:
            options["binary_unavailable"] = True
        if isinstance(binary, str) and not binary.startswith("[") and binary.lower().endswith(".py"):
            options["binary"] = str(Path(binary).expanduser().resolve())
        else:
            options["binary"] = prefix_argv[0] if len(prefix_argv) == 1 else prefix_argv
        home_key = kind + "_home"
        home = options.get(home_key) or os.environ.get(prefix + "_HOME") or os.environ.get(kind.upper() + "_HOME")
        if kind == "codex" and home is None:
            home = str(Path.home() / ".codex")
        options[home_key] = str(Path(home).expanduser().resolve()) if home else None
        options["frozen_config"] = True
        if sources is not None:
            for key, env in (("binary", prefix + "_BIN"), (home_key, prefix + "_HOME")):
                source_key = "workers.%s.%s" % (role, key)
                if key not in local and not (base and base.kind == kind and key in base.options):
                    sources[source_key] = (env if os.environ.get(env) else kind.upper() + "_HOME"
                                           if key == home_key and os.environ.get(kind.upper() + "_HOME") else "backend default")
    return WorkerSpec(kind, options)


LIMIT_FIELDS = {"max_tokens", "max_wall_seconds"}


def validate_limits(values: dict) -> dict:
    """null/missing means unlimited; reject ambiguous or nonfinite caps."""
    if not isinstance(values, dict) or set(values) - LIMIT_FIELDS:
        raise OPCError("budget allows only max_tokens and max_wall_seconds")
    for key, value in values.items():
        if value is None:
            continue
        if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                or (key == "max_tokens" and type(value) is not int)):
            raise OPCError("%s must be a positive %s or null" %
                           (key, "integer" if key == "max_tokens" else "number"))
    return values


def load_budget_config(root: Path) -> dict:
    """Read explicit local resource configuration."""
    return _load_config(root).get("budget", {})


def resolve_budget_limits(contract: dict, local: dict) -> dict:
    """Null cannot discard an existing explicit cap; missing time defaults to two hours."""
    values = {"max_tokens": None, "max_wall_seconds": 7200}
    values.update({k: contract[k] for k in LIMIT_FIELDS if k in contract})
    for key, value in local.items():
        if value is not None or contract.get(key) is None:
            values[key] = value
    return validate_limits(values)
