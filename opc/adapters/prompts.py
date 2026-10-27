"""Prompts for model workers. Domain-neutral: every domain fact comes from ctx."""
from __future__ import annotations

import json
from typing import Any


def _history(ctx: dict[str, Any]) -> str:
    rows = ctx.get("history") or []
    if not rows:
        return "(no previous attempts)"
    return json.dumps(rows, ensure_ascii=False, indent=2)


#: Appended only for a worker that has to parse the reply out of free text (dsh).
#: Codex constrains the shape through --output-schema, so it needs none of this, and
#: saying "no fence" there would contradict the schema channel rather than help it.
TEXT_REPLY_RULES = """Output only the JSON object. Legacy NO_EXPERIMENT is understood,
but use the JSON stop object to preserve conclusions and stop_reason."""

EXHAUSTION_RULE = """Decide whether any worthwhile work remains toward the task, including
capability development and diagnosis, within the budget. Reaching a target or a
streak without gain is information for your decision. If finished, set "exhausted":
true and give stop_reason after interpreting relevant results; otherwise set it false."""


def expert_prompt(ctx: dict[str, Any], plain_text_reply: bool = False) -> str:
    rules = (TEXT_REPLY_RULES if plain_text_reply else "") + "\n" + EXHAUSTION_RULE
    return """You are the EXPERT. Read research.json for the current task, budget,
working version, relevant history and evidence references. That file is the single
presentation of the context. Choose one worthwhile step or stop. The designer
locates code and implements your plan; do not investigate source code or raw logs.
You may read relevant research notes and structured evidence at the supplied paths.
An accepted improvement does not by itself establish its proposed mechanism.
Missing measurements are unmeasured, never zero. Cached results are historical,
not new measurements. Execution failure alone does not refute a hypothesis.
Interpret relevant results in conclusions [{"attempt": 1, "conclusion": "interpretation"}];
you need not clear every pending conclusion. Decide next work in the same reply.
base_attempt: null uses the default working version (champion for numeric tasks),
0 uses the initial baseline, positive numbers select any saved candidate, including
ones outside the recent view. Selection also applies when stopping.
Return title and changes describing one executable step, or exhausted=true with stop_reason.
Research fields may be empty. evaluate=null defaults to formal evaluation for numeric
tasks and local designer validation otherwise; true requests formal evaluation, false
skips it. A step may include continuous implementation, local testing and fixes.
Research fields may describe
conditions, controls, expected observations and uncertainty. Do not invent evidence.
""" + rules


def designer_prompt(plan: dict[str, Any], ctx: dict[str, Any]) -> str:
    comp = ctx["component"]
    return f"""You are the DESIGNER role in an automatic optimization loop. Implement exactly
the plan below in this working tree. Read code and locate the relevant files. A
measurement or diagnosis may need no code edit.

Rules:
- Edit implementation only in these paths: {json.dumps(comp['editable'])}.
- Generated scratch paths: {json.dumps(comp.get('scratch') or [])}. Local checks may write
  these outputs; they are discarded and never included in the candidate patch. Frozen
  tests/evaluators and .opc/ remain protected even if a scratch pattern matches them.
- Development tests within editable paths may be changed. Do not touch frozen
  tests, evaluators, golden data or anything under .opc/.
- Do not run `git commit`; leave changes in the working tree.
- Complete the step with continuous implementation, local checks and fixes.
  Formal frozen evaluation, when requested, happens elsewhere.
- Run checks unchanged; do not monkeypatch evaluators or suppress their report writes.
  If a check requires undeclared outputs, report that limitation instead of altering it.

## Plan
{json.dumps(plan, ensure_ascii=False, indent=2)}

## Objective context
Goal: {ctx['task']['goal']}
Numeric champion (when applicable): {json.dumps(ctx.get('champion'))}

Actual development parent: {json.dumps(ctx.get('parent') or {})}

When done, summarize actual behavior, design deviations, capability changes and
execution limitations. Official measurements run separately.
"""
