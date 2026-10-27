"""Codex CLI worker: `codex exec --json`, one fresh session per role call.

The expert runs read-only in a research-material directory with a JSON output schema;
the designer runs workspace-write inside its own tree. Every call records its
thread id (the call identity) and token usage from the event stream. Codex does
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
    executed = False
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
            tokens += int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        if t in ("turn.failed", "error"):
            failed = failed or t == "turn.failed"
            msg = ev.get("message") or (ev.get("error") or {}).get("message") or ""
            errors.append(msg)
        item = ev.get("item") or {}
        if t in ("item.started", "item.completed") and item.get("type") in (
                "command_execution", "mcp_tool_call", "file_change", "agent_message"):
            executed = True
        if t == "item.completed" and item.get("type") == "agent_message":
            last_agent = item.get("text", "")
    return {"thread_id": thread, "tokens": tokens, "errors": errors, "failed": failed,
            "last_agent": last_agent, "executed": executed}


class CodexWorker:
    def __init__(self, options: dict[str, Any]):
        self.model = options.get("model")
        self.reasoning_effort = options.get("reasoning_effort")
        if options.get("provider"):
            raise OPCError("codex uses its CLI provider configuration; provider is only for dsh")
        self.profile = options.get("profile")
        self.timeout = float(options.get("timeout_s", 1800))
        self.extra = list(options.get("extra_args") or [])
        self.binary = options.get("binary") or os.environ.get("OPC_CODEX_BIN")
        if not self.binary:
            # npm's codex.cmd may shadow a native CLI later on PATH. Never run
            # the batch wrapper through a shell, or override an explicit choice.
            self.binary = (shutil.which("codex.exe") if sys.platform == "win32" else None) or "codex"

    def _run(self, role: str, prompt: str, tree: Path, log_dir: Path, sandbox: str,
             schema: dict | None) -> tuple[WorkerCall, str]:
        log_dir.mkdir(parents=True, exist_ok=True)
        last = log_dir / ("%s-last.txt" % role)
        argv = [*command_prefix(self.binary), "exec", "--json", "--skip-git-repo-check", "-s", sandbox,
                "-C", str(tree), "-o", str(last)]
        if schema is not None:
            write_json(log_dir / "plan.schema.json", schema)
            argv += ["--output-schema", str(log_dir / "plan.schema.json")]
        if self.profile:
            argv += ["-p", self.profile]
        extra = list(self.extra)
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
        argv += extra + ["-"]
        if self.reasoning_effort:
            argv[-1:-1] = ["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)]
        # Explicit role settings outrank legacy extra_args overrides.
        if self.model:
            argv[-1:-1] = ["-m", self.model]
        write_text(log_dir / ("%s-prompt.md" % role), prompt)
        write_json(log_dir / ("%s-request.json" % role), {"argv": argv, "cwd": str(tree)})
        t0 = time.time()
        with open(log_dir / ("%s-events.jsonl" % role), "wb") as out, \
                open(log_dir / ("%s-stderr.txt" % role), "wb") as err:
            try:
                p = Process(argv, cwd=str(tree), stdin=subprocess.PIPE, stdout=out, stderr=err)
            except OSError as exc:
                return WorkerCall(role, False, Cost(time.time() - t0, 0, None),
                                  error="codex could not start: %s" % exc,
                                  extra={"infra": True}), ""
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
                          log_dir=str(log_dir))
        if timed_out:
            call.error, call.extra["infra"] = "codex timed out after %ss" % self.timeout, True
        elif info["failed"] or p.returncode != 0:
            stderr = (log_dir / ("%s-stderr.txt" % role)).read_text(
                errors="replace", encoding="utf-8")
            msg = "; ".join(e for e in info["errors"] if e) or stderr.strip() or \
                  "codex exited %s" % p.returncode
            infra = not info["thread_id"] or any(m.lower() in msg.lower() for m in INFRA_MARKERS)
            msg = msg[-2000:]
            call.error = msg
            call.extra["infra"] = infra or request_rejected(msg, info["executed"])
        else:
            call.ok = True
        return call, text

    def propose(self, ctx: dict[str, Any], tree: Path, log_dir: Path) -> WorkerCall:
        call, text = self._run("expert", expert_prompt(ctx), tree, log_dir, "read-only",
                               PLAN_SCHEMA)
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
                               "workspace-write", None)
        call.output = {"summary": text[-2000:]}
        return call
