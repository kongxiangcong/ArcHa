"""Machine-local model settings and optional resource caps."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .model import OPCError

ROLES = ("expert", "designer", "reviewer", "onboard")
CONFIG_PATH = ".opc/local/workers.json"
FIELDS = {"model", "reasoning_effort", "provider", "codex_home"}


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


def load_worker_config(root: Path) -> dict[str, dict[str, str]]:
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
            if not isinstance(value, str) or not value.strip():
                raise OPCError("%s: %s.%s must be a nonempty string or null" % (path, role, key))
            result[role][key] = value
    return result


def worker_options(config: dict[str, dict[str, str]], role: str,
                   base: dict[str, Any] | None = None) -> dict[str, Any]:
    """A null/missing local value inherits the role's task/backend configuration."""
    return {**(base or {}), **config.get(role, {})}


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
    """Explicit local limits override legacy contract fields, including null."""
    return _load_config(root).get("budget", {})
