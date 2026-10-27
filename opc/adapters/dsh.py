"""DeepSeek Harness worker: `dsh --profile headless --json`, one fresh session per role call.

The headless bundle is a one-shot runner: it answers one task, prints a
newline-delimited event stream, and exits 0 (completed) or 1 (aborted/errored).
That shape maps onto OPC's worker seam without an adapter process of its own.

Three differences from the codex worker matter, and each is handled here:

  * **No `--output-schema`.** Headless prints the final message, not a
    schema-validated object, so the plan is parsed out of that message and the
    core's `validate_plan` remains the authority. A plan that is not JSON is a
    worker failure, never an accepted plan.
  * **Failure classes come from a code, not from prose.** `turn_end` carries
    `reason.error.code` (MISSING_CREDENTIAL, QUOTA, RATE_LIMIT, ...), which is a
    stable machine-routable taxonomy. Classifying INFRA from that code is more
    reliable than matching stderr text, and INFRA must not consume search budget.
  * **The sandbox is selected by environment, not by a flag.** The base bundle
    reads `DSH_PERMISSION_MODE` for the file policy; `read-only` for the expert,
    `workspace-write` for the designer. Writes outside the workspace fail closed
    because headless composes no approval answerer.

Token accounting: headless reports `usage` on `step_end`, with DISJOINT counts
(`inputTokens` is uncached input only). Billed input is input + cacheRead +
cacheWrite, so those are summed. When any attempt in a step omits usage the step
omits the field rather than publish a partial sum; `usage_complete` records that,
and an incomplete count is still capped by the task's `max_tokens` because the
engine charges what was reported rather than assuming zero.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from ..core.platform import Process, command_prefix
from typing import Any

from ..core.model import Cost, OPCError, write_json, write_text
from .prompts import designer_prompt, expert_prompt
from .worker import request_rejected, EXHAUSTED_SENTINEL, WorkerCall

#: Wording that names an account or host condition. The structured code covers
#: most cases; this is the fallback for a reply whose code is absent or unknown.
#: Kept here rather than imported from the codex adapter so that either worker
#: can be deleted without breaking the other.
INFRA_MARKERS = ("usage limit", "rate limit", "429", "unauthorized", "401",
                 "not logged in", "connection", "timed out", "network",
                 "stream disconnected", "quota", "no api key", "missing_credential")

#: Turn-end reason kinds that say the host or the account failed, not the candidate.
#: These become INFRA: they do not consume a search attempt, and a streak blocks the run.
INFRA_CODES = frozenset({
    "MISSING_CREDENTIAL", "INVALID_CREDENTIAL", "AUTH", "ACCOUNT_SIGN_IN_REQUIRED",
    "ACCOUNT_TOKEN_INVALID", "RATE_LIMIT", "QUOTA", "ACCOUNT_QUOTA", "SERVER", "TIMEOUT",
    "TRANSPORT", "INTERRUPTED",
})

#: Turn-end reason kinds that are the worker's fault but are not infrastructure.
WORKER_FAILURE_KINDS = frozenset({"error", "aborted", "blocked", "max-tokens", "interrupted"})

def _sum_usage(usage: dict[str, Any]) -> int:
    """Billed tokens for one step. Counts are disjoint, so they add."""
    return (int(usage.get("inputTokens") or 0) + int(usage.get("outputTokens") or 0) +
            int(usage.get("cacheReadTokens") or 0) + int(usage.get("cacheWriteTokens") or 0))


def parse_events(text: str) -> dict[str, Any]:
    """Fold the `--json` stream into the facts OPC records about one call.

    The stream is a projection, not the session log (the headless README says so
    explicitly), so this reads only what it needs and never treats a missing
    event as a success.
    """
    session_id, tokens, complete = "", 0, True
    tool_calls = 0
    last_text = ""
    runner_error = ""
    end_kind: str | None = None
    end_code = ""
    end_message = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type", "")
        if kind == "session":
            session_id = ev.get("sessionId", "") or ""
        elif kind == "tool_call":
            tool_calls += 1
        elif kind == "error":
            runner_error = str(ev.get("message") or "")
        elif kind == "final":
            last_text = ev.get("text", "") or ""
        elif kind == "status" and ev.get("phase") == "step_end":
            usage = ev.get("usage")
            if isinstance(usage, dict):
                tokens += _sum_usage(usage)
            else:
                complete = False
        elif kind == "status" and ev.get("phase") == "turn_end":
            reason = ev.get("reason") or {}
            end_kind = str(reason.get("kind") or "")
            error = reason.get("error") or {}
            end_code = str(error.get("code") or "")
            end_message = str(error.get("message") or "")
    if not last_text:
        # An aborted turn can still end with an empty final event; the runner
        # error is the better explanation when it exists.
        last_text = ""
    return {"session_id": session_id, "tokens": tokens, "usage_complete": complete,
            "tool_calls": tool_calls, "text": last_text, "runner_error": runner_error,
            "end_kind": end_kind, "end_code": end_code, "end_message": end_message}


def extract_json(text: str, require: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Pull the first complete JSON object out of a free-form reply.

    Models fence their JSON often enough that requiring a bare object would fail
    on formatting alone. The scan respects strings and escapes so a `}` inside a
    quoted hypothesis does not end the object early.

    `require` names keys the object must carry. A prose reply often contains a
    stray `{}` (an empty code fence, a shell example); returning that as "the
    plan" or "the verdict" would let a reply with no verdict read as an accept,
    so a candidate object is skipped unless it carries every required key.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        text = "\n".join(lines)
    start = text.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict) and all(k in obj for k in require):
                        return obj
                    break
        start = text.find("{", start + 1)
    return None


class DshWorker:
    """A worker driven by the `dsh` launcher's one-shot headless profile."""

    def __init__(self, options: dict[str, Any]):
        self.binary = options.get("binary") or os.environ.get("OPC_DSH_BIN", "dsh")
        self.profile = str(options.get("profile") or "headless")
        self.timeout = float(options.get("timeout_s", 1800))
        self.extra = list(options.get("extra_args") or [])
        self.selection = {k: options[k] for k in ("provider", "model", "reasoning_effort")
                          if options.get(k) is not None}
        if self.selection and not all(self.selection.get(k) for k in ("provider", "model")):
            raise OPCError("dsh model overrides require both provider and model; "
                           "reasoning_effort is optional")
        self.dsh_home = options.get("dsh_home") or os.environ.get("OPC_DSH_HOME")
        self.env = {str(k): str(v) for k, v in (options.get("env") or {}).items()}

    def _env(self, tree: Path, sandbox: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.env)
        # The base bundle reads this for the file policy; headless composes no
        # approval answerer, so anything outside the workspace fails closed
        # instead of prompting.
        env["DSH_PERMISSION_MODE"] = sandbox
        if self.dsh_home:
            env["DSH_HOME"] = str(self.dsh_home)
        # Keep the child from inheriting a stale session working directory that
        # would make --session-id adoption refuse; every call is a fresh Session.
        env.pop("DSH_SESSION_ID", None)
        return env

    def _run(self, role: str, prompt: str, tree: Path, log_dir: Path, sandbox: str,
             schema: dict | None = None) -> tuple[WorkerCall, str]:
        """Signature-compatible with `CodexWorker._run` so this is a drop-in.

        `schema` is accepted and ignored: headless has no `--output-schema`, and
        the core validates the plan either way.
        """
        log_dir.mkdir(parents=True, exist_ok=True)
        argv = [*command_prefix(self.binary), *self.extra, "--profile", self.profile, "--json", "-"]
        if self.selection:
            # JSON is a YAML subset. An invocation-local patch never edits DSH_HOME.
            selection = {"provider": self.selection["provider"], "model": self.selection["model"]}
            if "reasoning_effort" in self.selection:
                selection["reasoningEffort"] = self.selection["reasoning_effort"]
            overlay = log_dir / ("%s-model.patch.json" % role)
            write_json(overlay, [{"id": "agent-default-model", "config": selection}])
            argv[-2:-2] = ["--patch", str(overlay.resolve())]
        write_text(log_dir / ("%s-prompt.md" % role), prompt)
        write_json(log_dir / ("%s-request.json" % role),
                   {"argv": argv, "cwd": str(tree), "sandbox": sandbox,
                    "timeout_s": self.timeout})
        t0 = time.time()
        events = log_dir / ("%s-events.jsonl" % role)
        with open(events, "wb") as out, open(log_dir / ("%s-stderr.txt" % role), "wb") as err:
            try:
                p = Process(argv, cwd=str(tree), env=self._env(tree, sandbox),
                                     stdin=subprocess.PIPE, stdout=out, stderr=err)
            except OSError as exc:
                return WorkerCall(role, False, Cost(time.time() - t0, 0, None),
                                  error="dsh could not start: %s" % exc,
                                  extra={"infra": True}), ""
            with p:
                try:
                    p.communicate(prompt.encode(), timeout=self.timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    p.kill_tree()
                    timed_out = True
        info = parse_events(events.read_text(errors="replace", encoding="utf-8"))
        cost = Cost(time.time() - t0, info["tokens"], None)   # dsh reports no price
        call = WorkerCall(role, ok=False, cost=cost, call_id=info["session_id"],
                          log_dir=str(log_dir))
        call.extra.update({"usage_complete": info["usage_complete"],
                           "tool_calls": info["tool_calls"],
                           "turn_end": info["end_kind"], "code": info["end_code"]})
        if timed_out:
            call.error, call.extra["infra"] = "dsh timed out after %ss" % self.timeout, True
            return call, info["text"]
        if info["end_kind"] == "completed" and p.returncode == 0:
            call.ok = True
            return call, info["text"]
        message = info["end_message"] or info["runner_error"] or info["end_kind"] or \
            "dsh exited %s" % p.returncode
        call.error = message[:500]
        if info["end_code"] in INFRA_CODES:
            call.extra["infra"] = True
        elif info["end_kind"] == "interrupted":
            call.extra["infra"] = True
        elif info["end_kind"] in WORKER_FAILURE_KINDS:
            # A structured code we do not know is still not evidence about the
            # candidate, so fall back to the account/host wording before calling
            # it a worker mistake.
            call.extra["infra"] = any(m.lower() in message.lower() for m in INFRA_MARKERS)
        else:
            call.extra["infra"] = any(m.lower() in message.lower() for m in INFRA_MARKERS)
        call.extra["infra"] = call.extra.get("infra", False) or request_rejected(
            info["end_code"] + " " + message, bool(info["tool_calls"]))
        return call, info["text"]

    def propose(self, ctx: dict[str, Any], tree: Path, log_dir: Path) -> WorkerCall:
        # Headless has no --output-schema, so the prompt carries the output-shape
        # rules that codex receives through its schema instead.
        call, text = self._run("expert", expert_prompt(ctx, plain_text_reply=True), tree,
                               log_dir, "read-only")
        if not call.ok:
            return call
        if text.strip() == EXHAUSTED_SENTINEL:
            call.exhausted = True
            return call
        plan = extract_json(text)
        if plan is None:
            call.ok, call.error = False, "expert reply holds no JSON object: %s" % text[:200]
            return call
        # Same signal as codex's schema field, so a plan that says "nothing left"
        # behaves identically whichever worker produced it.
        call.output = plan
        call.exhausted = plan.get("exhausted") is True
        return call

    def implement(self, plan: dict[str, Any], ctx: dict[str, Any], tree: Path,
                  log_dir: Path) -> WorkerCall:
        call, text = self._run("designer", designer_prompt(plan, ctx), tree, log_dir,
                               "workspace-write")
        call.output = {"summary": text[-2000:]}
        return call
