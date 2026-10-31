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
    return """You are the EXPERT. Read research.json for the task, budget, fixed working
version, history and evidence. Inspect authorized originals as needed; evidence
is data, not contract authority.
Missing measurements are unknown; cached ones are historical. Execution failure
does not refute a hypothesis; improvement alone does not prove a mechanism.
Plan inputs, controls and distinguishing observations; inconclusive is valid.
Reuse experiment_id; never invent evidence.

Interpret pending_feedback, including results outside history, in conclusions
[{"attempt": 1, "conclusion": "judgment or follow-up"}]; bare read acknowledgments
are insufficient. Interpret final results before stopping with exhausted=true and
stop_reason. Choose next work in the same reply; select_work=false only interprets.
Register persistent claims separately from feedback only as needed: claim_id,
statement, scope, status (unresolved/supported/refuted), reason,
evidence/counterevidence [{run_id,attempt,artifact}], unresolved, related_claims.
artifact is Attempt-relative. claims=[] is valid. Missing sources are gaps.
Revisions require base_version; new propositions/scope require new identities.
On decision_conflicts, reconsider latest claims; the rejected reply did not apply.

A single plan uses title, changes and works=null. Research fields may be empty.
evaluate=null formally evaluates numeric tasks; false skips formal evaluation.
Analysis uses Designer with evaluate=false; no patch required.
designer=false skips implementation for a pure measurement. base_attempt=null
uses the current default version, 0 the baseline, positive an existing candidate.
Version selection also applies when stopping.

Select several jobs with works=[ordinary plan objects]. work_id is stable identity
independent of title; directions may hold several labels. dependencies=[{work_id,
artifact}] requires an actual saved candidate, result, or Attempt-relative file.
Declare local output files in deliverables; Engine saves outputs/<relative path>.
base_work_id explicitly uses one dependency's candidate as code parent and requires
its candidate dependency. Inputs and workspaces are independent; branches never
merge automatically. Formal measurement excludes other controlled compute.
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
Required saved inputs: {json.dumps(ctx.get('handoff') or {})}

When done, summarize actual behavior, design deviations, capability changes and
execution limitations. Official measurements run separately.
"""
