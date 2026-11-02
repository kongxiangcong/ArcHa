"""Versioned presentation contract, used to validate responses and generate OpenAPI.

Enums deliberately remain open strings: future source states/roles degrade safely.
No persistence or execution protocol is defined here.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class DTO(BaseModel):
    model_config = ConfigDict(extra='allow')


class Issue(DTO):
    code: str
    message: str
    entity_id: str | None = None


class SourceRef(DTO):
    kind: str
    display_path: str
    locator: str | None = None
    artifact_id: str | None = None


class EntityMeta(DTO):
    availability: str
    source_refs: list[SourceRef] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)


class Ref(DTO):
    id: str
    label: str


class Entity(DTO):
    id: str
    meta: EntityMeta


class ObservedState(DTO):
    value: str
    raw_value: str | None = None
    basis: str
    at: str | None = None
    note: str | None = None


class TextFact(DTO):
    text: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class UsageView(DTO):
    scope: str
    scope_id: str
    includes_preparation: bool | None = None
    recorded_tokens: int | None = None
    recorded_usd: float | None = None
    recorded_wall_seconds: float | None = None
    completeness: str
    budget_tokens: int | None = None
    budget_wall_seconds: float | None = None
    note: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)


class Requirement(DTO):
    id: str
    required: bool = True
    text: str
    verification: str | None = None
    result: str
    tested_commit: str | None = None
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    report_artifact_id: str | None = None


class Metric(DTO):
    name: str
    unit: str | None = None
    direction: str | None = None
    threshold: Any = None
    baseline: float | None = None
    candidate: float | None = None
    champion: float | None = None
    selected: float | None = None
    comparison_state: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class Project(Entity):
    project_key: str
    display_name: str
    source_project_id: str | None = None
    source_format: str | None = None
    source_runtime_version: str | None = None
    adapter_id: str
    adapter_version: str
    source_mode: str


class ResearchTask(Entity):
    title: str
    research_task_id: str | None = None
    map_artifact_id: str | None = None
    task_artifact_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    raw_preparation_status: str | None = None
    briefs: list[Ref] = Field(default_factory=list)
    revision_refs: list[Ref] = Field(default_factory=list)
    link_state: str


class Brief(Entity):
    path: str
    sha256: str | None = None
    source_kind: str
    source_task_id: str | None = None
    body_artifact_id: str | None = None
    goal: str | None = None
    done_when: str | None = None
    scope: str | None = None
    deliverables: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    objective: Any = None
    link_state: str


class TaskRevision(Entity):
    research_task_id: str | None = None
    ownership_state: str = 'unresolved'
    brief_bindings: list[dict[str, Any]] = Field(default_factory=list)
    execution_task_id: str
    revision: str
    task_digest: str | None = None
    goal: str | None = None
    requirements: list[Requirement] = Field(default_factory=list)
    objective: Any = None
    budget: dict[str, Any] | None = None
    brief_id: str | None = None
    link_state: str
    contract_artifact_id: str | None = None


class Run(Entity):
    source_run_id: str
    kind: str
    task_revision_id: str | None = None
    execution_task_id: str | None = None
    preparation: ObservedState
    execution: ObservedState
    acceptance: ObservedState
    acceptance_history: list[dict[str, Any]] = Field(default_factory=list)
    stop_reason: str | None = None
    phase: str
    last_activity_at: str | None = None
    versions: dict[str, str | None]
    requirements: list[Requirement] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    usage: UsageView | None = None
    attempts: list[Ref] = Field(default_factory=list)
    calls: list[Ref] = Field(default_factory=list)
    artifacts: list[Ref] = Field(default_factory=list)
    report_refs: list[Ref] = Field(default_factory=list)
    pending_feedback: list[int] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    max_concurrency: int | None = None


class Attempt(Entity):
    run_id: str
    attempt_no: int
    phase: str
    execution_state: ObservedState
    outcome: str | None = None
    intent: TextFact | None = None
    rationale: TextFact | None = None
    execution_summary: TextFact | None = None
    experiment_summary: TextFact | None = None
    conclusion: TextFact | None = None
    gaps: TextFact | None = None
    next_step: TextFact | None = None
    parent_commit: str | None = None
    candidate_commit: str | None = None
    work_id: str | None = None
    directions: list[str] = Field(default_factory=list)
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    resource_wait: str | None = None
    feedback_state: str = "pending"
    selected_by_call: str | None = None
    reviewed_by_call: str | None = None
    calls: list[Ref] = Field(default_factory=list)
    artifacts: list[Ref] = Field(default_factory=list)
    usage: UsageView | None = None


class Call(Entity):
    run_id: str | None = None
    attempt_id: str | None = None
    phase: str
    role: str
    provider: str | None = None
    provider_call_id: str | None = None
    parent_call_id: str | None = None
    state: ObservedState
    started_at: str | None = None
    ended_at: str | None = None
    last_activity_at: str | None = None
    transcript_availability: str
    artifacts: list[Ref] = Field(default_factory=list)
    usage: UsageView | None = None


class Artifact(Entity):
    kind: str
    title: str
    display_path: str
    content_origin: str
    owner_refs: list[Ref] = Field(default_factory=list)
    phase: str
    availability: str
    mime: str | None = None
    size_bytes: int | None = None
    digest: str | None = None
    digest_algorithm: str | None = None
    key_facts: list[TextFact] = Field(default_factory=list)
    can_preview: bool
    can_download: bool


class CallContentItem(DTO):
    id: str
    call_id: str
    sequence: int
    at: str | None = None
    kind: str
    role: str | None = None
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    payload: Any = None
    state: ObservedState | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)


class CallContent(DTO):
    call_id: str
    items: list[CallContentItem]
    reset: bool
    reset_reason: str | None = None


class ArtifactContent(DTO):
    artifact_id: str
    content: str
    encoding: str
    byte_offset: int
    next_offset: int
    eof: bool
    truncated: bool
    content_version: str


class Overview(DTO):
    project: Project
    maps: list[Ref]
    tasks: list[ResearchTask]
    unlinked_revisions: list[Ref]
    unlinked_runs: list[Ref]
    capabilities: dict[str, str]


class ResearchDetail(DTO):
    task: ResearchTask
    briefs: list[Brief]
    revisions: list[TaskRevision]
    runs: list[Ref]
    artifacts: list[Artifact]


class RevisionDetail(DTO):
    revision: TaskRevision
    runs: list[Ref]
    artifacts: list[Artifact]


class ControlCapability(DTO):
    enabled: bool
    reason: str


class WorkerSummary(DTO):
    id: str
    attempt_no: int | None
    role: str
    state: str
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    activity_available: bool
    activity_note: str


class WorkItem(DTO):
    id: str
    attempt_no: int
    work_id: str
    title: str
    goal: str | None = None
    stage: str
    reason: str | None = None
    dependencies: list[dict]
    blocked_by: list[str]
    calls: list[str]
    summary: str | None = None
    outcome: str | None = None
    needs_attention: bool
    availability: str


class WorkItems(DTO):
    items: list[WorkItem]
    total: int
    scope: str


class ControlRequestView(DTO):
    request_id: str
    run_id: str
    action: str
    status: str
    sequence: int
    reason: str
    created_at: str
    updated_at: str
    run: dict


class Workbench(DTO):
    id: str
    display_label: str
    source_run_id: str
    execution: str
    goal: str | None = None
    stop_reason: str | None = None
    result: dict
    control: dict[str, ControlCapability]
    control_request: ControlRequestView | None = None
    workers: list[WorkerSummary]
    workers_truncated: bool
    work_count: int
    availability: str
    observation_note: str


class ToolAction(DTO):
    id: str
    category: str
    name: str | None = None
    object: str | None = None
    state: str
    started_at: str | None = None
    ended_at: str | None = None
    summary: str | None = None
    exit_code: int | None = None


class CallActivity(DTO):
    call_id: str
    actions: list[ToolAction]
    availability: str
    note: str | None = None
    reset: bool
    truncated: bool
    has_more: bool


class TaskMaterial(DTO):
    id: str
    name: str
    purpose: str
    availability: str
    note: str | None = None


class Inspection(DTO):
    attempt_no: int
    calls: list[WorkerSummary]
    call_id: str | None
    error: str | None
    input: dict | None
    output: dict | None
    input_note: str
    materials: list[TaskMaterial]
    material_note: str | None = None


T = TypeVar('T')


class Envelope(DTO, Generic[T]):
    schema_version: str = '1.0'
    snapshot_at: str
    source_observed_at: str | None = None
    data: T
    issues: list[Issue] = Field(default_factory=list)
    next_cursor: str | None = None
