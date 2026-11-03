"""Prompts for model workers. Domain-neutral: every domain fact comes from ctx."""
from __future__ import annotations

import json
from typing import Any
from .worker import PROGRESS_RULE


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

EXHAUSTION_RULE = """Continue by gaps, evidence and expected value, not fixed no-gain counts or spare budget.
finish=null continues; finish="request_acceptance" runs checks and required independent
review on the candidate; prior review is not needed. finish="close_incomplete" stops.
Interpret pending results. Require stop_reason; incomplete needs gaps and grounded
reopen_conditions ([] if none). Legacy "exhausted"=true closes incomplete."""


def expert_prompt(ctx: dict[str, Any], plain_text_reply: bool = False) -> str:
    rules = (TEXT_REPLY_RULES if plain_text_reply else "") + "\n" + EXHAUSTION_RULE
    if ctx.get("decision_correction"):
        rules += ("\nRepair decision_correction.rejected_output using its reason; return a complete decision. "
                  "The rejected reply was not applied or executed. Corrections consume the same budget.")
    return """EXPERT: Read research.json.
Read authorized originals; keep contracts.
knowledge.command: --claim-id/--status/--text/--source.
Missing = unknown; cached = historical. Failure is not refutation;
improvement is not mechanism evidence. Plan controls/predictions; allow inconclusive.
Reuse experiment_id; never invent evidence.

Interpret pending_feedback and historical_pending_feedback in conclusions
[{"run_id":null,"attempt":1,"conclusion":"judgment or follow-up"}]; null means current
Run. Use [] when none are pending; no fabricated attempt. Fix decision_rejections.
select_work=false only interprets; final_feedback_only=true saves analysis without work.
claims=[] is valid; otherwise use claim_id, statement, scope, status
(unresolved/supported/refuted), reason, evidence/counterevidence [{run_id,attempt,artifact}],
unresolved, related_claims. artifact is Attempt-relative. Missing originals limit claims;
new data cannot replace required historical execution.
Revisions use base_version; new propositions/scope use new IDs.
Work adopted_claims=[{task_id,claim_id,version}] declares adoption; reading does not.
On decision_conflicts reconsider latest claims; rejected replies were unapplied.
basis_review: echo attempt/changes, action continue/adjust/supplement, scope/reason.
continue: select_work=false; adjust: one replacement plan; supplement: extra work first.
Review basis_changes.
delivery_repair gives source, candidate, gaps and next_step; repair within this contract.

Plan: title/changes. evaluate=null runs numeric tasks; false skips.
designer=false measures only. base_attempt: null default, 0 baseline,
positive saved candidate; also at finish.
At acceptance: delivery_claims=[{task_id,claim_id,version}],
delivery_artifacts=[{run_id,attempt,artifact}], distinct from adopted_claims.
Changed delivery basis needs delivery_basis_review={action,scope,reason,changes}.

Batch: works=[plans], work_id, directions, dependencies=[{work_id,artifact}].
Dependencies need saved originals. deliverables: concrete relative editable/scratch
files, never directories/globs (tools/check.py, not tools); saved as outputs/<path>.
New files are allowed.
base_work_id selects a candidate dependency. Branches need explicit selection, never
auto-merge. Formal measurement excludes other compute.
""" + rules + "\n" + PROGRESS_RULE


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
""" + PROGRESS_RULE
