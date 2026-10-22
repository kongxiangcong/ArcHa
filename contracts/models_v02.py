"""OPC v0.2: project binding and requirement-to-verification traceability.

v0.1 stays in models.py; this module does not migrate or authorize old runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from models import (
    Acceptance,
    ArtifactRef,
    AxisReview,
    Budget,
    Claim,
    Contract,
    Digest,
    Nonempty,
    Permissions,
    SourceRef,
)
from pydantic import AfterValidator, Field, model_validator


def safe_id(value: str) -> str:
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if value in reserved:
        raise ValueError("reserved Windows device name")
    return value


Id = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$"), AfterValidator(safe_id)]


class ProjectConfig(Contract):
    schema_version: Literal["opc.project.v0.2"]
    project_id: Id
    display_name: Nonempty
    protocol_version: Literal["opc.v0.2"]
    control_root: Literal[".opc"]
    components: list[Id] = Field(min_length=1)
    adapter_id: Id
    artifact_store_alias: Literal["artifacts"]
    workspace_store_alias: Literal["workspaces"]
    baseline_policy: Literal["clean_commit_or_explicit_snapshot"]
    execution_enabled: bool

    @model_validator(mode="after")
    def configured(self) -> ProjectConfig:
        if len(set(self.components)) != len(self.components):
            raise ValueError("duplicate component id")
        if self.execution_enabled and self.adapter_id == "unconfigured":
            raise ValueError("cannot enable an unconfigured project")
        return self


def relative_path(value: str) -> str:
    if value == ".":
        return value
    if "\\" in value or ":" in value or value.startswith("/") or any(
        part in ("", ".", "..") for part in value.rstrip("/").split("/")
    ):
        raise ValueError("use a project-relative POSIX path without traversal")
    return value


RelativePath = Annotated[str, Field(min_length=1), AfterValidator(relative_path)]


class ToolCommand(Contract):
    command_id: Id
    argv: list[Nonempty] = Field(min_length=1)
    cwd: RelativePath
    timeout_seconds: int = Field(ge=1)
    resource_ref: str | None


class ComponentConfig(Contract):
    schema_version: Literal["opc.component.v0.2"]
    component_id: Id
    description: Nonempty
    adapter_id: Id
    source_roots: list[RelativePath]
    editable_paths: list[RelativePath]
    frozen_paths: list[RelativePath]
    commands: list[ToolCommand]
    input_refs: list[SourceRef]
    readiness: Literal["draft", "configured"]

    @model_validator(mode="after")
    def executable_configuration(self) -> ComponentConfig:
        ids = [c.command_id for c in self.commands]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate command id")
        if self.readiness == "configured" and (
            self.adapter_id == "unconfigured" or not self.commands or not self.source_roots
        ):
            raise ValueError("configured component requires an adapter, sources and commands")
        for path in self.editable_paths:
            if path.rstrip("/") in (".", ".opc", ".git") or path.startswith((".opc/", ".git/")):
                raise ValueError("control metadata cannot be an editable component path")
        return self


class Baseline(Contract):
    kind: Literal["git_commit", "source_snapshot"]
    source_ref: SourceRef
    git_commit: Annotated[str, Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")] | None
    includes_dirty_changes: bool
    snapshot_manifest: ArtifactRef | None

    @model_validator(mode="after")
    def reproducible(self) -> Baseline:
        if self.kind == "git_commit" and (self.git_commit is None or self.includes_dirty_changes):
            raise ValueError("git baseline must name a clean commit")
        if self.kind == "source_snapshot" and self.snapshot_manifest is None:
            raise ValueError("non-git/dirty baseline requires an explicit snapshot manifest")
        return self


class Requirement(Contract):
    requirement_id: Id
    statement: Nonempty
    current_state: Nonempty
    target_state: Nonempty
    negative_constraints: list[Nonempty]
    category: Literal["functional", "performance", "research", "reproducibility", "integration"]
    priority: Literal["must", "should"]
    source_refs: list[SourceRef] = Field(min_length=1)
    success_criterion: Nonempty
    verification_mode: Literal["automated", "independent_review", "human_judgment"]


class ContextDecisions(Contract):
    locked: list[Nonempty]
    delegated: list[Nonempty]
    deferred: list[Nonempty]
    canonical_refs: list[SourceRef]


class Observable(Contract):
    check_id: Id
    requirement_ids: list[Id] = Field(min_length=1)
    observation: Nonempty
    verification: Nonempty


class ExpectedArtifact(Contract):
    artifact_id: Id
    requirement_ids: list[Id] = Field(min_length=1)
    logical_path: Nonempty
    purpose: Nonempty


class KeyLink(Contract):
    link_id: Id
    requirement_ids: list[Id] = Field(min_length=1)
    producer_artifact_id: Id
    consumer_artifact_id: Id
    verification: Nonempty


class MustHaves(Contract):
    observables: list[Observable] = Field(min_length=1)
    artifacts: list[ExpectedArtifact] = Field(min_length=1)
    key_links: list[KeyLink]


class Dependency(Contract):
    task_id: Id
    task_revision: int = Field(ge=1)
    accepted_submission_id: Id
    manifest_sha256: Digest
    required_interface: Nonempty


class TaskSpecV02(Contract):
    schema_version: Literal["opc.taskspec.v0.2"]
    project_id: Id
    component_id: Id
    task_id: Id
    revision: int = Field(ge=1)
    parent_task_id: Id | None
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
    baseline: Baseline
    requirements: list[Requirement] = Field(min_length=1)
    context: ContextDecisions
    must_haves: MustHaves
    dependencies: list[Dependency]

    @model_validator(mode="after")
    def traceable(self) -> TaskSpecV02:
        ids = [r.requirement_id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate requirement id")
        nodes: list[Observable | ExpectedArtifact | KeyLink] = [
            *self.must_haves.observables, *self.must_haves.artifacts, *self.must_haves.key_links]
        seen = set()
        for node in nodes:
            if not set(node.requirement_ids) <= set(ids):
                raise ValueError("must-have references an unknown requirement")
            seen.update(node.requirement_ids)
        if set(ids) - seen:
            raise ValueError("requirements without a must-have")
        checks: list[Observable | KeyLink] = [*self.must_haves.observables, *self.must_haves.key_links]
        verified_ids = {rid for item in checks
                        for rid in item.requirement_ids}
        if set(ids) - verified_ids:
            raise ValueError("artifact presence alone cannot verify a requirement")
        for values in (
            [x.check_id for x in self.must_haves.observables],
            [x.artifact_id for x in self.must_haves.artifacts],
            [x.link_id for x in self.must_haves.key_links],
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate must-have identifier")
        artifact_ids = {x.artifact_id for x in self.must_haves.artifacts}
        check_ids = [x.check_id for x in self.must_haves.observables] + [x.link_id for x in self.must_haves.key_links]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("observable and key-link identifiers must be distinct")
        for link in self.must_haves.key_links:
            if not {link.producer_artifact_id, link.consumer_artifact_id} <= artifact_ids:
                raise ValueError("key link references an unknown artifact")
        return self


class RunBinding(Contract):
    project_id: Id
    task_id: Id
    task_revision: int = Field(ge=1)
    task_spec_sha256: Digest
    run_id: Id


class ExperimentPlanV02(RunBinding):
    schema_version: Literal["opc.plan.v0.2"]
    plan_id: Id
    attempt_id: Id
    requirement_ids: list[Id] = Field(min_length=1)
    parent_submission_id: Id | None
    evidence_refs: list[ArtifactRef]
    hypothesis: Nonempty
    competing_explanation: Nonempty
    change: Nonempty
    controlled_variables: list[Nonempty] = Field(min_length=1)
    falsification: Nonempty
    files_modified: list[Nonempty]
    files_deleted: list[Nonempty]
    expected_artifact_ids: list[Id] = Field(min_length=1)
    measurement_commands: list[list[Nonempty]] = Field(min_length=1)
    predicted_model_usd_upper_bound: float = Field(ge=0)
    predicted_wall_seconds: int = Field(ge=1)


class Coverage(Contract):
    requirement_id: Id
    status: Literal["pass", "fail", "partial", "unverified", "needs_human"]
    check: Nonempty
    verified_check_ids: list[Id]
    evidence: list[ArtifactRef]
    human_judgment: bool
    limitation: str | None

    @model_validator(mode="after")
    def evidence_before_pass(self) -> Coverage:
        if self.status == "pass" and (not self.evidence or not self.verified_check_ids or self.human_judgment):
            raise ValueError("automatic pass requires evidence and no unresolved human judgment")
        return self


class ArtifactBinding(Contract):
    artifact_id: Id
    status: Literal["present", "missing"]
    artifact_ref: ArtifactRef | None
    reason: str | None

    @model_validator(mode="after")
    def explicit_presence(self) -> ArtifactBinding:
        if self.status == "present" and self.artifact_ref is None:
            raise ValueError("present artifact requires a concrete reference")
        if self.status == "missing" and (self.artifact_ref is not None or not self.reason):
            raise ValueError("missing artifact requires a reason and no invented reference")
        return self


class SubmissionV02(RunBinding):
    schema_version: Literal["opc.submission.v0.2"]
    submission_id: Id
    attempt_id: Id
    plan_id: Id
    producer_call_id: Nonempty
    manifest_sha256: Digest
    artifacts: list[ArtifactRef] = Field(min_length=1)
    artifact_bindings: list[ArtifactBinding] = Field(min_length=1)
    claims: list[Claim]
    limitations: list[Nonempty]
    failed_checks: list[Nonempty]
    environment_ref: ArtifactRef
    coverage: list[Coverage] = Field(min_length=1)
    deviations: list[Nonempty]
    provides: list[Nonempty]
    affects: list[Nonempty]


class ReviewDecisionV02(RunBinding):
    schema_version: Literal["opc.review.v0.2"]
    review_id: Id
    review_call_id: Nonempty
    submission_id: Id
    manifest_sha256: Digest
    standards: AxisReview
    spec: AxisReview
    recommended_disposition: Literal["accept", "revise", "reject", "blocked"]
    conclusion: Nonempty
    accepted_claims: list[Claim]
    coverage: list[Coverage] = Field(min_length=1)
    unknowns: list[Nonempty]
    gaps: list[Nonempty]
    checked_manifest_sha256: Digest

    @model_validator(mode="after")
    def consistent_review(self) -> ReviewDecisionV02:
        if self.manifest_sha256 != self.checked_manifest_sha256:
            raise ValueError("reviewed manifest differs from submitted manifest")
        if self.recommended_disposition == "accept" and (
            self.standards.verdict != "pass" or self.spec.verdict != "pass" or
            self.gaps or any(x.status != "pass" for x in self.coverage)
        ):
            raise ValueError("accept requires both axes and all claimed coverage to pass, without gaps")
        return self


def check_bundle(task: TaskSpecV02, plan: ExperimentPlanV02, submission: SubmissionV02,
                 review: ReviewDecisionV02) -> list[str]:
    """Semantic preflight for linked payloads, NOT an authorization/acceptance service."""
    import hashlib

    spec_hash = hashlib.sha256(json.dumps(task.model_dump(mode="json"), sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    errors = []
    for item in (plan, submission, review):
        if (item.project_id, item.task_id, item.task_revision, item.task_spec_sha256) != (
            task.project_id, task.task_id, task.revision, spec_hash
        ):
            errors.append("task/project/revision/digest mismatch")
    if len({plan.run_id, submission.run_id, review.run_id}) != 1:
        errors.append("run mismatch")
    if plan.plan_id != submission.plan_id or plan.attempt_id != submission.attempt_id:
        errors.append("plan/attempt mismatch")
    if (review.submission_id, review.manifest_sha256) != (submission.submission_id, submission.manifest_sha256):
        errors.append("submission binding mismatch")
    requirements = {x.requirement_id for x in task.requirements}
    if not set(plan.requirement_ids) <= requirements:
        errors.append("unknown plan requirement")
    if not set(plan.expected_artifact_ids) <= {x.artifact_id for x in task.must_haves.artifacts}:
        errors.append("unknown planned artifact")
    artifact_ids = [x.artifact_id for x in submission.artifact_bindings]
    declared_artifacts = {x.artifact_id for x in task.must_haves.artifacts}
    if len(artifact_ids) != len(set(artifact_ids)) or not set(artifact_ids) <= declared_artifacts:
        errors.append("duplicate or unknown artifact binding")
    if not set(plan.expected_artifact_ids) <= set(artifact_ids):
        errors.append("planned artifact must be explicitly present or missing")
    actual_refs = {x.model_dump_json() for x in submission.artifacts}
    for bound in submission.artifact_bindings:
        if bound.status == "present" and bound.artifact_ref is not None and bound.artifact_ref.model_dump_json() not in actual_refs:
            errors.append("bound artifact is absent from submitted artifact manifest list")
    present = {x.artifact_id for x in submission.artifact_bindings if x.status == "present"}
    for item in (submission, review):
        ids = [x.requirement_id for x in item.coverage]
        if len(ids) != len(set(ids)) or set(ids) != requirements:
            errors.append("coverage must enumerate each task requirement exactly once")
        for row in item.coverage:
            expected = {x.check_id for x in task.must_haves.observables if row.requirement_id in x.requirement_ids}
            expected |= {x.link_id for x in task.must_haves.key_links if row.requirement_id in x.requirement_ids}
            if not set(row.verified_check_ids) <= expected:
                errors.append("coverage references an unknown check")
            if row.status == "pass" and not expected <= set(row.verified_check_ids):
                errors.append("passed requirement lacks an observable or integration check")
            required_artifacts = {x.artifact_id for x in task.must_haves.artifacts if row.requirement_id in x.requirement_ids}
            if row.status == "pass" and not required_artifacts <= present:
                errors.append("passed requirement lacks a concrete required artifact binding")
    # Evidence authenticity, paths, current files, identity, budget and hard gates remain service checks.
    return errors


MODELS: tuple[type[Contract], ...] = (
    ProjectConfig, ComponentConfig, TaskSpecV02, ExperimentPlanV02, SubmissionV02, ReviewDecisionV02)


def export(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for cls in MODELS:
        (root / f"{cls.__name__}.schema.json").write_text(
            json.dumps(cls.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export(Path(__file__).parent / "schemas/v0.2")
