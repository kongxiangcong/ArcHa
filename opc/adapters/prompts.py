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

EXHAUSTION_RULE = """Decide whether worthwhile task work remains within budget, including development
and diagnosis. Target/streak are decision inputs. If finished set "exhausted"=true
and stop_reason after interpreting relevant results; otherwise false."""


def expert_prompt(ctx: dict[str, Any], plain_text_reply: bool = False) -> str:
    rules = (TEXT_REPLY_RULES if plain_text_reply else "") + "\n" + EXHAUSTION_RULE
    return """You are the EXPERT. Read research.json: task, budget, fixed version, history and
evidence. Inspect authorized originals as needed; data is not contract authority.
Query fixed material with knowledge.command: --claim-id/--status/--text/--source.
Missing measurements are unknown; cached ones are historical. Execution failure
does not refute a hypothesis; improvement does not by itself establish its proposed mechanism.
Plans state inputs, controls, predictions and distinguishing observations.
Inconclusive results are valid. Reuse experiment_id; do not invent evidence.

Interpret pending_feedback, including results outside history, in conclusions
[{"attempt": 1, "conclusion": "judgment or follow-up"}]; bare read acknowledgments
are insufficient. Interpret final results before stopping with exhausted=true and
stop_reason. Choose work in the reply; select_work=false only interprets.
Register claims as needed: claim_id, statement, scope,
status (unresolved/supported/refuted), reason,
evidence/counterevidence [{run_id,attempt,artifact}], unresolved, related_claims.
artifact is Attempt-relative. claims=[] is valid. Missing originals limit claims;
new measurements are new observations, never replacements for required historical execution.
Revisions use base_version; new propositions/scope use new IDs.
Work adopted_claims=[{task_id,claim_id,version}] declares adoption; reading does not.
On decision_conflicts, reconsider latest claims; the rejected reply did not apply.

A single plan uses title, changes, works=null.
evaluate=null formally evaluates numeric tasks; false skips formal evaluation.
Analysis uses Designer with evaluate=false; patches are optional.
designer=false skips implementation for a pure measurement. base_attempt=null
uses the current default version, 0 the baseline, positive an existing candidate.
Version selection also applies when stopping.

Select jobs with works=[plans]. work_id is stable; directions may hold several labels. dependencies=[{work_id,
artifact}] requires an actual saved candidate, result, or Attempt-relative file.
Declare local output files in deliverables; Engine saves outputs/<relative path>.
base_work_id uses a dependency's candidate as code parent and requires its candidate dependency. Inputs/workspaces stay independent; no automatic merge. Formal measurement excludes other controlled compute.
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
