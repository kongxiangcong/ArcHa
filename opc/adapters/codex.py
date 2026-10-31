"""Codex CLI worker: `codex exec --json`, explicit Expert session continuation.

The expert runs read-only in a research-material directory with a JSON output schema;
the designer runs workspace-write inside its own tree. Every call records its
native thread id (separate from the Engine Call identity) and token usage from the event stream. Codex does
not report prices, so usd stays None (unknown) and budgets must cap tokens.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..core.platform import Process, command_prefix
from ..core.tool_boundary import worker_policy, codex_policy_args, validate_cli_boundary_args
from typing import Any

from ..core.model import Cost, OPCError, write_json, write_text
from .prompts import designer_prompt, expert_prompt
from .worker import EXHAUSTED_SENTINEL, PLAN_SCHEMA, WorkerCall, request_rejected

#: account/host conditions: retrying the attempt cannot help, the run must block
INFRA_MARKERS = ("usage limit", "rate limit", "429", "unauthorized", "401", "not logged in",
                 "Connection", "timed out", "network", "stream disconnected", "quota",
                 "error loading config", "requires a newer version of codex",
                 "failed to initialize in-process app-server")


def parse_events(text: str) -> dict[str, Any]:
    thread, tokens, errors, failed, last_agent = "", 0, [], False, ""
    unmetered_nested = False
    usage_complete = False
    executed = False
    completed = False
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type", "")
        if t == "thread.started":
            thread = ev.get("thread_id", "")
        usage = ev.get("usage")
        if isinstance(usage, dict):
            usage_complete = "input_tokens" in usage and "output_tokens" in usage
            tokens += int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        if t == "turn.completed":
            completed = True
        if t in ("turn.failed", "error"):
            failed = failed or t == "turn.failed"
            msg = ev.get("message") or (ev.get("error") or {}).get("message") or ""
            errors.append(msg)
        item = ev.get("item") or {}
        if "collab" in item.get("type", ""):
            unmetered_nested = True
        if item.get("type") == "command_execution":
            import re
            if re.search(r"\b(codex|dsh)(?:\.exe)?\s", item.get("command", "")):
                unmetered_nested = True
        if t in ("item.started", "item.completed") and item.get("type") in (
                "command_execution", "mcp_tool_call", "file_change", "agent_message"):
            executed = True
        if t == "item.completed" and item.get("type") == "agent_message":
            last_agent = item.get("text", "")
    return {"thread_id": thread, "tokens": tokens, "errors": errors, "failed": failed,
            "last_agent": last_agent, "executed": executed, "terminal_completed": completed and not failed, "usage_complete": usage_complete and not unmetered_nested}


class CodexWorker:
    def __init__(self, options: dict[str, Any]):
        self.session_id: str | None = None
        self.tool_scope = {"tool_policy": options["tool_policy"]} if "tool_policy" in options else {}
        self.binary_unavailable = options.get("binary_unavailable", False)
        self.native_selection_error = options.get("native_selection_error")
        self.model = options.get("model")
        self.reasoning_effort = options.get("reasoning_effort")
        if options.get("provider"):
            raise OPCError("codex uses its CLI provider configuration; provider is only for dsh")
        self.profile = options.get("profile")
        self.native_defaults_frozen = options.get("native_defaults_frozen", False)
        self.native_model_provider = options.get("native_model_provider")
        self.native_provider_config = options.get("native_provider_config", {})
        self.codex_home = options.get("codex_home") if options.get("frozen_config") else options.get("codex_home") or os.environ.get("OPC_CODEX_HOME")
        self.timeout = options.get("timeout_s")
        if self.timeout is not None:
            self.timeout = float(self.timeout)
        self.extra = list(options.get("extra_args") or [])
        self.binary = options.get("binary") or os.environ.get("OPC_CODEX_BIN")
        if not self.binary:
            # npm's codex.cmd may shadow a native CLI later on PATH. Never run
            # the batch wrapper through a shell, or override an explicit choice.
            self.binary = (shutil.which("codex.exe") if sys.platform == "win32" else None) or "codex"

    def _run(self, role: str, prompt: str, tree: Path, log_dir: Path, sandbox: str,
             schema: dict | None, *, ctx: dict | None = None) -> tuple[WorkerCall, str]:
        t0 = time.time()
        try:
            session_id = (ctx or {}).get("session_id", self.session_id)
            env = os.environ.copy()
            if self.codex_home:
                home = Path(self.codex_home).expanduser()
                if not home.is_absolute() or not home.is_dir():
                    raise OPCError("codex_home must name an existing absolute directory with Codex configuration/auth")
                env["CODEX_HOME"] = str(home)
            log_dir.mkdir(parents=True, exist_ok=True)
            last = log_dir / ("%s-last.txt" % role)
            last.unlink(missing_ok=True)
            argv = [*command_prefix(self.binary), "--no-daemon", "exec", "--json", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
                    "-C", str(tree), "-o", str(last)]
            if self.profile and not self.native_defaults_frozen:
                argv += ["-p", self.profile]
            if role == "expert" and session_id:
                # cwd/permissions/profile are parent exec options; resume accepts the
                # explicit native identity and inherits these execution constraints.
                argv += ["resume"]
            if schema is not None:
                write_json(log_dir / "plan.schema.json", schema)
                argv += ["--output-schema", str(log_dir / "plan.schema.json")]
            extra = list(self.extra)
            validate_cli_boundary_args("codex", extra)
            policy = worker_policy(role, tree, log_dir, ctx or self.tool_scope)
            policy["read"].append(str(Path(shutil.which(command_prefix(self.binary)[0]) or command_prefix(self.binary)[0]).resolve()))
            write_json(log_dir / "tool-policy.json", policy)
            prompt += "\nTask tool boundary: only paths in tool-policy.json grants are available. " + json.dumps({k: policy[k] for k in ('read', 'write', 'limitations')})
            if self.model:
                # Model is a single-valued clap option; duplicate -m is an error.
                filtered, i = [], 0
                while i < len(extra):
                    arg = extra[i]
                    if arg in ("-m", "--model"):
                        i += 2
                        continue
                    if not (arg.startswith("--model=") or (arg.startswith("-m") and len(arg) > 2)):
                        filtered.append(arg)
                    i += 1
                extra = filtered
            argv += extra + codex_policy_args(policy)
            if self.native_model_provider:
                argv += ["-c", "model_provider=" + json.dumps(self.native_model_provider)]
                for key, value in self.native_provider_config.items():
                    argv += ["-c", "model_providers.%s.%s=%s" % (json.dumps(self.native_model_provider), key, json.dumps(value))]
            argv +=  ([session_id] if role == "expert" and session_id else []) + ["-"]
            if self.reasoning_effort:
                argv[-1:-1] = ["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)]
            # Explicit role settings outrank legacy extra_args overrides.
            if self.model:
                argv[-1:-1] = ["-m", self.model]
            write_text(log_dir / ("%s-prompt.md" % role), prompt)
            write_json(log_dir / ("%s-request.json" % role), {"argv": argv, "cwd": str(tree),
                       "codex_home": env.get("CODEX_HOME", str(Path.home() / ".codex"))})
        except (OPCError, OSError, ValueError) as exc:
            return WorkerCall(role, False, Cost(time.time() - t0, 0, None),
                              error="codex task tool boundary could not be prepared: " + str(exc),
                              log_dir=str(log_dir), extra={"infra": True, "not_started": True,
                                  "usage_complete": True, "capability_gap": True}), ""
        with open(log_dir / ("%s-events.jsonl" % role), "wb") as out, \
                open(log_dir / ("%s-stderr.txt" % role), "wb") as err:
            try:
                if self.binary_unavailable:
                    executable = Path(command_prefix(self.binary)[0])
                    if not executable.is_absolute() or not executable.is_file():
                        raise FileNotFoundError("configured executable was unavailable when this Run was frozen: %s" % self.binary)
                if self.native_selection_error:
                    raise OSError(self.native_selection_error)
                p = Process(argv, cwd=str(tree), env=env, stdin=subprocess.PIPE, stdout=out, stderr=err)
            except OSError as exc:
                return WorkerCall(role, False, Cost(time.time() - t0, 0, None),
                                  error="codex could not start: %s" % exc,
                                  extra={"infra": True, "usage_complete": True, "not_started": True}), ""
            with p:
                try:
                    p.communicate(prompt.encode(), timeout=self.timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    p.kill_tree()
                    timed_out = True
        info = parse_events((log_dir / ("%s-events.jsonl" % role)).read_text(errors="replace", encoding="utf-8"))
        cost = Cost(time.time() - t0, info["tokens"], None)
        text = last.read_text(errors="replace", encoding="utf-8") if last.exists() else info["last_agent"]
        call = WorkerCall(role, ok=False, cost=cost, call_id=info["thread_id"],
                          log_dir=str(log_dir), extra={"usage_complete": info["usage_complete"],
                                                    "session_id": info["thread_id"] or (session_id if role == "expert" else None),
                                                    "terminal_completed": info["terminal_completed"],
                                                    "tool_policy": str(log_dir / "tool-policy.json"),
                                                    "tool_boundary": "codex native permission profile", "boundary_limitations": policy["limitations"]})
        if p.cancel_reason and info["terminal_completed"]:
            call.ok = True
        elif p.cancel_reason:
            call.error = p.cancel_reason
            call.extra.update(cancelled=True, infra=True)
        elif timed_out:
            call.error, call.extra["infra"] = "codex timed out after %ss" % self.timeout, True
        elif info["failed"] or p.returncode != 0:
            stderr = (log_dir / ("%s-stderr.txt" % role)).read_text(
                errors="replace", encoding="utf-8")
            msg = "; ".join(e for e in info["errors"] if e) or stderr.strip() or \
                  "codex exited %s" % p.returncode
            infra = not info["thread_id"] or any(m.lower() in msg.lower() for m in INFRA_MARKERS)
            msg = msg[-2000:]
            if "read-only file system" in msg.lower() or "readonly filesystem" in msg.lower():
                msg += ("; Codex state directory may be read-only in the outer sandbox. "
                        "Configure OPC_CODEX_HOME or workers.json codex_home to an existing writable "
                        "Codex home with the intended config/auth, or relaunch in an authorized writable "
                        "environment. Inner -s workspace-write cannot grant outer filesystem access.")
            call.error = msg
            call.extra["infra"] = infra or request_rejected(msg, info["executed"])
        elif info["terminal_completed"]:
            call.ok = True
        else:
            call.error = "codex exited without a reliable terminal event"
            call.extra.update(infra=True, execution_unknown=True)
        if not info["thread_id"] and not info["executed"] and "thread/start failed" in call.error:
            call.extra.update(not_started=True, usage_complete=True, capability_gap=True)
            call.error = "Codex could not establish the task tool boundary before model dispatch: " + call.error
        if (role == "expert" and session_id and not info["executed"]
                and any(marker in call.error.lower() for marker in
                        ("no rollout found", "no session found", "session not found", "session does not exist"))):
            call.extra.update(session_unavailable=True, not_started=True, usage_complete=True)
        elif not info["terminal_completed"] and not info["failed"] and not call.extra.get("not_started"):
            call.extra["execution_unknown"] = True
        return call, text

    def propose(self, ctx: dict[str, Any], tree: Path, log_dir: Path) -> WorkerCall:
        call, text = self._run("expert", expert_prompt(ctx), tree, log_dir, "read-only",
                               PLAN_SCHEMA, ctx=ctx)
        if call.ok:
            # The output schema admits only a plan object, so the text sentinel dsh
            # uses is unreachable here. The schema-valid equivalent is the optional
            # "exhausted": true field; accept the sentinel too, because a worker that
            # answers in prose still means the same thing.
            if text.strip() == EXHAUSTED_SENTINEL:
                call.exhausted = True
                return call
            try:
                plan = json.loads(text)
            except json.JSONDecodeError:
                call.ok, call.error = False, "expert reply is not JSON: %s" % text[:200]
                return call
            call.output = plan
            call.exhausted = isinstance(plan, dict) and plan.get("exhausted") is True
        return call

    def implement(self, plan: dict[str, Any], ctx: dict[str, Any], tree: Path,
                  log_dir: Path) -> WorkerCall:
        call, text = self._run("designer", designer_prompt(plan, ctx), tree, log_dir,
                               "workspace-write", None, ctx=ctx)
        call.output = {"summary": text[-2000:]}
        return call
