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
true and give stop_reason after reviewing pending results; otherwise set it false."""


def expert_prompt(ctx: dict[str, Any], plain_text_reply: bool = False) -> str:
    task, comp = ctx["task"], ctx["component"]
    format_rules = (TEXT_REPLY_RULES if plain_text_reply else "") + "\n" + EXHAUSTION_RULE
    return f"""You are the EXPERT role in an automatic research loop. You design ONE
experiment or stop exploration. The designer reads and implements code; a frozen
evaluator measures results. You do not edit files or inspect source code.

## Task
Goal: {task['goal']}
User direction: {task.get('direction') or '(none)'}
Requirements: {json.dumps(task.get('requirements') or [], ensure_ascii=False)}
Acceptance: {task['acceptance']}
Component: {comp['id']}; {comp.get('description') or ''}
Focus: {ctx.get('focus') or '(free choice)'}

## Current champion
commit {ctx['champion']['commit'][:12]}; metrics: {json.dumps(ctx['champion']['values'])}
Baseline metrics: {json.dumps(ctx['baseline']['values'])}

## Previous experiments
{_history(ctx)}

Use the original hypothesis, changes, expected effect and falsifier alongside actual
execution and experimental data. champion_before is the comparison baseline; parent
is the actual development starting point. Missing measurements mean unmeasured, not
zero or a refuted hypothesis. Failed implementation or execution alone does not refute
a hypothesis; an accepted improvement does not by itself establish its proposed mechanism.
cached=true means reused historical data, not a new measurement. started without a
completed result means incomplete execution, not evidence that the hypothesis failed.
First review each history row with conclusion=null. Return conclusions as
[{{"attempt": 1, "conclusion": "short interpretation of that original design and result"}}].
Mention support, uncertainty, deviations and capability changes where relevant.
These are your interpretations, not independent reviews. Do not invent measurements.
Then choose the next experiment or stop in this SAME reply. First round: conclusions=[].

## Progress signals
{json.dumps(ctx.get('progress') or {})}

## Budget left
{json.dumps(ctx.get('budget_left') or {})}

## Research background
{json.dumps(ctx.get('background') or {}, ensure_ascii=False, indent=2)}
The working directory contains only research materials. Work from background,
decisions, experimental data and conclusions. Do not seek code, raw logs or evaluator
verdicts. The designer locates files and implementation details.

Return a JSON object with title, hypothesis, changes (method, conditions, controls
and observations for the designer to implement), expected, falsifier, base_attempt
(null for champion, 0 for initial baseline, or an available candidate attempt number),
conclusions, exhausted, stop_reason. Code file paths are not required. When stopping,
experiment text may be empty; retain conclusions and stop_reason.
Available candidates: {json.dumps(ctx.get('candidates') or [])}
{format_rules}
"""


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
- Do not touch tests, evaluators, golden data or anything under .opc/.
- Do not run `git commit`; leave changes in the working tree.
- Keep the change minimal and self-consistent. If a quick local check exists you may run it,
  but the official evaluation happens elsewhere.
- Run checks unchanged; do not monkeypatch evaluators or suppress their report writes.
  If a check requires undeclared outputs, report that limitation instead of altering it.

## Plan
{json.dumps(plan, ensure_ascii=False, indent=2)}

## Objective context
Goal: {ctx['task']['goal']}
Champion metrics: {json.dumps(ctx['champion']['values'])}

Actual development parent: {json.dumps(ctx.get('parent') or {})}

When done, summarize actual behavior, design deviations, capability changes and
execution limitations. Official measurements run separately.
"""
