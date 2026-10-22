"""Prompts for model workers. Domain-neutral: every domain fact comes from ctx."""
from __future__ import annotations

import json
from typing import Any


def _history(ctx: dict[str, Any]) -> str:
    rows = ctx.get("history") or []
    if not rows:
        return "(no previous attempts)"
    lines = ["| # | title | files | outcome | gain | reason |", "|---|---|---|---|---|---|"]
    for h in rows:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            h.get("attempt"), (h.get("title") or "")[:60], ", ".join(h.get("files") or [])[:60],
            h.get("outcome"), "" if h.get("gain") is None else "%+.2f%%" % (100 * h["gain"]),
            (h.get("reason") or "").replace("|", "/").replace("\n", " ")[:160]))
    return "\n".join(lines)


#: Appended only for a worker that has to parse the reply out of free text (dsh).
#: Codex constrains the shape through --output-schema, so it needs none of this, and
#: saying "no fence" there would contradict the schema channel rather than help it.
TEXT_REPLY_RULES = """Output only that JSON object: no prose, no markdown fence, no commentary around it. A reply
that holds no JSON object is discarded and the attempt is wasted.
If you judge that no further experiment can improve the objective with the budget left, reply
with exactly NO_EXPERIMENT and nothing else, instead of repeating a refuted idea."""

#: The same exhaustion signal in the shape a schema-constrained worker can send.
#: Given to every model worker, because "stop when there is nothing left" is a
#: property of the role, not of one adapter.
EXHAUSTION_RULE = """If no further experiment can improve the objective with the budget left, set "exhausted":
true in the object and stop exploring, instead of repeating a refuted idea."""


def expert_prompt(ctx: dict[str, Any], plain_text_reply: bool = False) -> str:
    task, comp = ctx["task"], ctx["component"]
    domain_files = (ctx.get("domain") or {}).get("context_files") or {}
    docs = "\n\n".join("### %s\n```\n%s\n```" % (k, v) for k, v in domain_files.items())
    format_rules = (TEXT_REPLY_RULES if plain_text_reply else "") + "\n" + EXHAUSTION_RULE
    return f"""You are the EXPERT role in an automatic optimization loop. You propose ONE
experiment; another role implements it; a frozen evaluator judges it. You do not edit files.

## Task
Goal: {task['goal']}
User direction: {task.get('direction') or '(none)'}
Requirements: {json.dumps(task.get('requirements') or [], ensure_ascii=False)}
Acceptance: {task['acceptance']}

## Component `{comp['id']}`
{comp.get('description') or ''}
Editable paths (only these may change): {json.dumps(comp['editable'])}
Focus for this attempt: {ctx.get('focus') or '(free choice)'}

## Current champion
commit {ctx['champion']['commit'][:12]}; metrics: {json.dumps(ctx['champion']['values'])}
Baseline metrics: {json.dumps(ctx['baseline']['values'])}

## Previous attempts (do not repeat a refuted idea; learn from failures)
{_history(ctx)}

## Lessons
{chr(10).join('- ' + l for l in ctx.get('lessons') or []) or '(none yet)'}

## Budget left
{json.dumps(ctx.get('budget_left') or {})}

## Project material
The working directory is a read-only checkout of the champion. Read whatever you need.
{docs}

Return a JSON object with: title, hypothesis, files (subset of editable paths), changes
(precise enough for another engineer to implement without guessing), expected (effect on the
objective and constraints), falsifier (what result would refute the hypothesis).
{format_rules}
"""


def designer_prompt(plan: dict[str, Any], ctx: dict[str, Any]) -> str:
    comp = ctx["component"]
    return f"""You are the DESIGNER role in an automatic optimization loop. Implement exactly
the plan below in this working tree.

Rules:
- Edit only these paths: {json.dumps(comp['editable'])}. Any other change fails the attempt.
- Do not touch tests, evaluators, golden data or anything under .opc/.
- Do not run `git commit`; leave changes in the working tree.
- Keep the change minimal and self-consistent. If a quick local check exists you may run it,
  but the official evaluation happens elsewhere.

## Plan
{json.dumps(plan, ensure_ascii=False, indent=2)}

## Objective context
Goal: {ctx['task']['goal']}
Champion metrics: {json.dumps(ctx['champion']['values'])}

When done, reply with a short summary of what you changed.
"""
