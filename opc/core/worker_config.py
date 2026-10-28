"""Machine-local role overrides, separate from versioned task contracts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import OPCError

ROLES = ("expert", "designer", "reviewer", "onboard")
CONFIG_PATH = ".opc/local/workers.json"
FIELDS = {"model", "reasoning_effort", "provider", "codex_home"}


def load_worker_config(root: Path) -> dict[str, dict[str, str]]:
    path = root / CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise OPCError("cannot read %s: %s" % (path, exc)) from exc
    if not isinstance(data, dict) or set(data) - set(ROLES):
        raise OPCError("%s: expected role objects: %s" % (path, ", ".join(ROLES)))
    result = {}
    for role, values in data.items():
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
