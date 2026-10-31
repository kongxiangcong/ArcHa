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
    if not isinstance(data, dict) or set(data) - set(ROLES) - {"budget", "max_concurrency"}:
        raise OPCError("%s: expected budget and role objects: %s" % (path, ", ".join(ROLES)))
    validate_limits(data.get("budget", {}))
    return data


def load_worker_config(root: Path) -> dict[str, dict[str, Any]]:
    path = root / CONFIG_PATH
    data = _load_config(root)
    result = {}
    for role, values in data.items():
        if role in ("budget", "max_concurrency"):
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



def _freeze_codex_defaults(options: dict, role: str, sources: dict | None) -> None:
    """Flatten only model routing/settings; native tools, permissions and credentials stay out."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10 uses the standard TOML backport.
        import tomli as tomllib
    extra = options.get("extra_args", [])
    for index, arg in enumerate(extra):
        assignment = (extra[index + 1] if arg in ("-c", "--config") and index + 1 < len(extra)
                      else arg[9:] if arg.startswith("--config=") else arg[2:] if arg.startswith("-c") else "")
        key = assignment.split("=", 1)[0].strip()
        model_flag = arg in ("-m", "--model") or arg.startswith("--model=") or (arg.startswith("-m") and len(arg) > 2)
        profile_flag = arg in ("-p", "--profile") or arg.startswith("--profile=") or (arg.startswith("-p") and len(arg) > 2)
        unsupported = (profile_flag or arg in ("--oss", "--local-provider") or arg.startswith("--local-provider=")
                       or key in ("profile", "model_provider", "model_providers")
                       or key.startswith("model_providers.")
                       or ((model_flag or key == "model") and not options.get("model"))
                       or (key == "model_reasoning_effort" and not options.get("reasoning_effort")))
        if unsupported:
            raise OPCError("Codex model/provider/profile overrides must use role fields or native configuration, not extra_args, so the Run can freeze their selection")
    path = Path(options["codex_home"]) / "config.toml"
    try:
        with path.open("rb") as stream:
            native = tomllib.load(stream)
    except FileNotFoundError:
        native = {}
    except (OSError, ValueError) as exc:
        raise OPCError("cannot resolve Codex native model configuration %s: %s" % (path, exc)) from exc
    profile_name = options.get("profile") or native.get("profile")
    if profile_name is not None and not isinstance(profile_name, str):
        raise OPCError("Codex native profile selection must be a string")
    selected = native
    if profile_name:
        profiles = native.get("profiles", {})
        if not isinstance(profiles, dict):
            raise OPCError("Codex native profiles must be a table")
        profile = profiles.get(profile_name)
        if not isinstance(profile, dict):
            raise OPCError("Codex native profile %r is unavailable in %s" % (profile_name, path))
        selected = {**native, **profile}
    options["native_profile"] = profile_name
    for field, native_field in (("model", "model"), ("reasoning_effort", "model_reasoning_effort")):
        value = selected.get(native_field)
        if field not in options and value is not None:
            if not isinstance(value, str) or not value.strip():
                raise OPCError("Codex native %s must be a nonempty string" % native_field)
            options[field] = value
            if sources is not None:
                sources["workers.%s.%s" % (role, field)] = str(path) + ("#profiles." + profile_name if profile_name else "")
    provider = selected.get("model_provider", "openai")
    if not isinstance(provider, str) or not provider:
        raise OPCError("Codex native model_provider must be a nonempty string")
    providers = selected.get("model_providers", {})
    if not isinstance(providers, dict):
        raise OPCError("Codex native model_providers must be a table")
    provider_config = providers.get(provider, {})
    if not isinstance(provider_config, dict):
        raise OPCError("Codex native provider configuration must be a table")
    supported = {"name", "base_url", "env_key", "wire_api", "requires_openai_auth",
                 "request_max_retries", "stream_max_retries", "stream_idle_timeout_ms"}
    if set(provider_config) - supported:
        raise OPCError("Codex native provider %s has unsupported settings; use supported routing and environment credential selectors, never inline credentials" % provider)
    if not provider_config and provider != "openai":
        raise OPCError("Codex native provider %s has no freezeable routing configuration" % provider)
    provider_config = dict(provider_config)
    if provider == "openai" and "base_url" not in provider_config and os.environ.get("OPENAI_BASE_URL"):
        provider_config["base_url"] = os.environ["OPENAI_BASE_URL"]
        if sources is not None:
            sources["workers.%s.native_provider_config.base_url" % role] = "OPENAI_BASE_URL"
    if provider_config.get("base_url"):
        from urllib.parse import urlsplit
        address = urlsplit(provider_config["base_url"])
        if address.username or address.password or address.query or address.fragment:
            raise OPCError("Codex provider base_url cannot freeze embedded credentials or query data; use an environment credential selector")
    options["native_model_provider"] = provider
    options["native_provider_config"] = dict(provider_config)
    options["native_defaults_frozen"] = True
    if not options.get("model"):
        options["native_selection_error"] = "Codex native model default is unknown; configure an explicit role model before creating a Run"
    if sources is not None:
        sources["workers.%s.native_model_provider" % role] = str(path)
        if profile_name:
            sources["workers.%s.native_profile" % role] = sources.get("workers.%s.profile" % role, str(path))

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
        if kind == "codex":
            _freeze_codex_defaults(options, role, sources)
        elif not (options.get("provider") and options.get("model")):
            options["native_selection_error"] = "DSH native defaults cannot be frozen by this adapter; configure explicit provider and model for this role before creating a Run"
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


def load_max_concurrency(root: Path, sources: dict | None = None) -> int:
    data = _load_config(root)
    value = data.get("max_concurrency", 3)
    if sources is not None:
        sources["max_concurrency"] = CONFIG_PATH if "max_concurrency" in data else "builtin:execution-v1"
    if type(value) is not int or value < 1:
        raise OPCError("max_concurrency must be a positive integer")
    return value
