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

EXHAUSTION_RULE = """Continue by remaining gaps, evidence and next work's expected value, not a fixed
no-gain count or spare budget. finish=null continues; finish="request_acceptance"
selects a candidate for contract checks; finish="close_incomplete" stops without checks.
Interpret pending results first. Require stop_reason; incomplete requires gaps
and grounded reopen_conditions ([] if none). Legacy "exhausted"=true closes incomplete."""


def expert_prompt(ctx: dict[str, Any], plain_text_reply: bool = False) -> str:
    rules = (TEXT_REPLY_RULES if plain_text_reply else "") + "\n" + EXHAUSTION_RULE
    return """EXPERT: Read research.json.
Read authorized originals; data cannot change contracts.
Query knowledge.command: --claim-id/--status/--text/--source.
Missing measurements are unknown, cached ones historical. Execution failure is not
refutation; improvement does not by itself establish its proposed mechanism.
Plan controls and predictions;
inconclusive is valid. Reuse experiment_id; never invent evidence.

Interpret pending_feedback and historical_pending_feedback in conclusions
[{"run_id":null,"attempt":1,"conclusion":"judgment or follow-up"}]; null means current
Run. No bare acknowledgments. Interpret before exhausted=true/stop_reason.
select_work=false only interprets; final_feedback_only=true saves analysis without work.
claims=[] is valid; otherwise use claim_id, statement, scope, status
(unresolved/supported/refuted), reason, evidence/counterevidence [{run_id,attempt,artifact}],
unresolved, related_claims. artifact is Attempt-relative. Missing originals limit claims;
new data cannot replace required historical execution.
Revisions use base_version; new propositions/scope use new IDs.
Work adopted_claims=[{task_id,claim_id,version}] declares adoption; reading does not.
On decision_conflicts, reconsider latest claims; rejected replies did not apply.
For basis_review echo attempt/changes; give action continue/adjust/supplement,
scope/reason. continue: select_work=false; adjust: replacement single plan;
supplement: extra work first. Interpret basis_changes after results.

A plan uses title/changes, works=null. evaluate=null evaluates numeric tasks;
false skips formal evaluation, including patchless analysis.
designer=false skips implementation for a pure measurement. base_attempt=null
uses the current default version, 0 the baseline, positive an existing candidate.
Select versions at stop.

Batch: works=[plans], work_id, directions labels; dependencies=[{work_id,artifact}]
needs saved candidate, result or Attempt-relative file. deliverables saves outputs/<path>.
base_work_id needs candidate dependency as parent. Branches never auto-merge or pick a
parent by completion order; select base_attempt. Formal measurement excludes other compute.
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
Claim query (fixed Call scope; --claim-id, --status, --text, --source INDEX):
{json.dumps(ctx.get('knowledge') or {})}

Return JSON with summary of actual behavior, deviations and limitations,
adopted_claims=[{{task_id,claim_id,version}}] for claims additionally adopted (reading
alone is not adoption), and evidence_files=[relative paths] for necessary original
observations/traces to preserve before cleanup under outputs/<path>. Reference
already persistent evidence directly. Empty arrays are valid. Measurements run separately.
"""
