"""OPC v0.1 contract proposal; not a deployed authorization service.

Run: python contracts/models.py --export
Dependencies: pydantic==2.12.5. JSON Schema and examples are generated together.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Nonempty = Annotated[str, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SourceRef(Contract):
    uri: Nonempty
    sha256: Digest
    locator: Nonempty


class ArtifactRef(Contract):
    uri: Nonempty
    sha256: Digest
    size_bytes: int = Field(ge=0)
    media_type: Nonempty
    producer_job_id: Nonempty


class Budget(Contract):
    max_attempts: int = Field(ge=1)
    max_review_calls: int = Field(ge=1)
    max_wall_seconds: int = Field(ge=1)
    model_usd_cap: float = Field(ge=0)
    model_tokens_cap: int = Field(ge=0)
    max_concurrent_jobs: int = Field(ge=1)
    unknown_price_policy: Literal["block"] = "block"
    inflight_at_limit: Literal["drain", "cancel_request"]


class Permissions(Contract):
    readable_roots: list[Nonempty] = Field(min_length=1)
    writable_roots: list[Nonempty] = Field(min_length=1)
    frozen_refs: list[SourceRef] = Field(min_length=1)
    allowed_tools: list[Nonempty] = Field(min_length=1)
    network: Literal["disabled", "allowlist"]
    network_allowlist: list[str]
    publish: Literal[False] = False
    modify_harness: Literal[False] = False

    @model_validator(mode="after")
    def check_network(self) -> Permissions:
        if self.network == "disabled" and self.network_allowlist:
            raise ValueError("disabled network requires empty allowlist")
        if self.network == "allowlist" and not self.network_allowlist:
            raise ValueError("allowlist network requires explicit hosts")
        return self


class Metric(Contract):
    metric_id: Nonempty
    unit: Nonempty
    direction: Literal["minimize", "maximize", "informational"]
    evidence_level: Literal["functional", "analytical", "simulation", "synthesis", "hardware"]
    aggregation: Nonempty
    target: float | None


class Acceptance(Contract):
    evaluator: SourceRef
    workloads: list[SourceRef] = Field(min_length=1)
    hard_gates: list[Nonempty] = Field(min_length=1)
    metrics: list[Metric]
    required_review_axes: list[Literal["standards", "spec"]] = Field(min_length=2, max_length=2)
    accept_conditional: bool
    evidence_ceiling: Literal["functional", "analytical", "simulation", "synthesis", "hardware"]

    @model_validator(mode="after")
    def check_axes(self) -> Acceptance:
        if set(self.required_review_axes) != {"standards", "spec"}:
            raise ValueError("both distinct review axes required")
        return self


class TaskSpec(Contract):
    schema_version: Literal["opc.taskspec.v0.1"]
    task_id: Nonempty
    revision: int = Field(ge=1)
    parent_task_id: str | None
    task_kind: Literal["research", "implement", "optimize"]
    objective: Nonempty
    source_requirements: list[SourceRef] = Field(min_length=1)
    scope_in: list[Nonempty] = Field(min_length=1)
    scope_out: list[Nonempty] = Field(min_length=1)
    deliverables: list[Nonempty] = Field(min_length=1)
    inputs: list[SourceRef]
    research_unknowns: list[Nonempty]
    open_decisions: list[Nonempty]
    acceptance: Acceptance
    budget: Budget
    permissions: Permissions
    stop_rules: list[Nonempty] = Field(min_length=1)
    authorization_ref: str | None
    domain: dict[str, object]

    def dispatch_problems(self) -> list[str]:
        # Server must separately resolve authorization_ref to a trusted record.
        issues = list(self.open_decisions)
        if not self.authorization_ref:
            issues.append("missing trusted authorization record")
        return issues


class Binding(Contract):
    task_id: Nonempty
    task_revision: int = Field(ge=1)
    task_spec_sha256: Digest


class ExperimentPlan(Binding):
    schema_version: Literal["opc.plan.v0.1"]
    plan_id: Nonempty
    parent_submission_id: str | None
    evidence_refs: list[ArtifactRef]
    hypothesis: Nonempty
    competing_explanation: Nonempty
    change: Nonempty
    controlled_variables: list[Nonempty] = Field(min_length=1)
    falsification: Nonempty
    measurement_commands: list[list[Nonempty]] = Field(min_length=1)
    expected_artifacts: list[Nonempty] = Field(min_length=1)
    predicted_model_usd_upper_bound: float = Field(ge=0)
    predicted_wall_seconds: int = Field(ge=1)


class Claim(Contract):
    statement: Nonempty
    conditions: list[Nonempty] = Field(min_length=1)
    evidence: list[ArtifactRef] = Field(min_length=1)
    level: Literal["functional", "analytical", "simulation", "synthesis", "hardware"]


class Submission(Binding):
    schema_version: Literal["opc.submission.v0.1"]
    submission_id: Nonempty
    attempt_id: Nonempty
    plan_id: Nonempty
    producer_call_id: Nonempty
    manifest_sha256: Digest
    artifacts: list[ArtifactRef] = Field(min_length=1)
    claims: list[Claim]
    limitations: list[Nonempty]
    failed_checks: list[Nonempty]
    environment_ref: ArtifactRef


class AxisReview(Contract):
    verdict: Literal["pass", "revise", "fail", "inconclusive"]
    findings: list[Nonempty]
    checked_artifacts: list[ArtifactRef] = Field(min_length=1)


class ReviewDecision(Binding):
    schema_version: Literal["opc.review.v0.1"]
    review_id: Nonempty
    review_call_id: Nonempty
    submission_id: Nonempty
    manifest_sha256: Digest
    standards: AxisReview
    spec: AxisReview
    recommended_disposition: Literal["accept", "revise", "reject", "blocked"]
    conclusion: Nonempty
    accepted_claims: list[Claim]
    unknowns: list[Nonempty]

    @model_validator(mode="after")
    def no_axis_override(self) -> ReviewDecision:
        if self.recommended_disposition == "accept" and (
            self.standards.verdict != "pass" or self.spec.verdict != "pass"
        ):
            raise ValueError("accept requires both axes to pass")
        return self


class DecisionRequest(Contract):
    schema_version: Literal["opc.decision.v0.1"]
    decision_id: Nonempty
    task_id: Nonempty
    expected_revision: int = Field(ge=1)
    reason: Literal["scope", "budget", "acceptance", "resource", "authorization"]
    question: Nonempty
    options: list[Nonempty] = Field(min_length=2)
    recommendation: Nonempty
    blocked_actions: list[Nonempty] = Field(min_length=1)


class JobRecord(Binding):
    schema_version: Literal["opc.job.v0.1"]
    job_id: Nonempty
    attempt_id: Nonempty
    role: Literal["expert", "designer", "experiment", "reviewer"]
    idempotency_key: Nonempty
    input_digest: Digest
    state: Literal["intent", "submitted", "running", "succeeded", "failed", "cancel_requested", "cancelled", "unknown"]
    backend_job_id: str | None
    runtime_call_id: str | None
    reserved_model_usd: float = Field(ge=0)
    actual_model_usd: float | None = Field(ge=0)
    result: ArtifactRef | None
    reconcile_note: str | None


def export(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for cls in (TaskSpec, ExperimentPlan, Submission, ReviewDecision, DecisionRequest, JobRecord):
        (root / f"{cls.__name__}.schema.json").write_text(
            json.dumps(cls.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    if args.export:
        export(Path(__file__).parent / "schemas")
