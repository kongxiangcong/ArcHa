export interface Ref {
  id: string;
  display_label?: string;
  label: string;
  kind?: string;
  revision?: string;
  recorded_state?: string | null;
  stop_reason?: string | null;
}
export interface Issue {
  code: string;
  message: string;
  entity_id?: string | null;
}
export interface SourceRef {
  kind: string;
  display_path: string;
  locator: string | null;
  artifact_id: string | null;
}
export interface Meta {
  availability: string;
  source_refs: SourceRef[];
  issues: Issue[];
}
export interface State {
  value: string;
  raw_value: string | null;
  basis: string;
  at: string | null;
  note: string | null;
}
export interface Envelope<T> {
  schema_version: string;
  snapshot_at: string;
  source_observed_at: string | null;
  data: T;
  issues: Issue[];
  next_cursor: string | null;
}
export interface Fact {
  text: string;
  source_refs: SourceRef[];
}
export interface Usage {
  scope: string;
  scope_id: string;
  includes_preparation: boolean | null;
  recorded_tokens: number | null;
  recorded_usd: number | null;
  recorded_wall_seconds: number | null;
  completeness: string;
  budget_tokens: number | null;
  budget_wall_seconds: number | null;
  note: string | null;
  source_refs: SourceRef[];
}
export interface Requirement {
  id: string;
  text: string;
  verification: string | null;
  result: string;
  tested_commit: string | null;
  evidence_refs: SourceRef[];
  report_artifact_id: string | null;
}
export interface Metric {
  scopes?: Record<string, Record<string, unknown>>;
  name: string;
  unit?: string;
  direction?: string;
  threshold?: unknown;
  baseline?: unknown;
  candidate?: unknown;
  champion?: unknown;
  selected?: unknown;
  comparison_state: string;
  source_refs: SourceRef[];
}
export interface Task extends Ref {
  topic: string;
  title: string;
  research_task_id: string | null;
  map_artifact_id: string | null;
  task_artifact_id: string | null;
  depends_on: (Ref | string)[];
  raw_preparation_status: string | null;
  briefs: Ref[];
  revision_refs: Ref[];
  link_state: string;
  meta: Meta;
}
export interface Revision extends Ref {
  research_task_id?: string | null;
  ownership_state?: string;
  brief_bindings?: { path: string; sha256: string | null }[];
  execution_task_id: string;
  revision: string;
  task_digest: string | null;
  goal: string | null;
  requirements: Requirement[];
  objective: unknown;
  budget: unknown;
  brief_id: string | null;
  link_state: string;
  contract_artifact_id: string | null;
  meta: Meta;
}
export interface Brief extends Ref {
  path: string;
  sha256: string | null;
  body_artifact_id: string | null;
  goal: string | null;
  done_when: string | null;
  scope: string | null;
  deliverables: unknown[];
  requirements: Requirement[];
  link_state: string;
  meta: Meta;
}
export interface Project {
  id: string;
  project_key: string;
  display_name: string;
  source_project_id: string | null;
  source_format: string | null;
  source_runtime_version: string | null;
  adapter_id: string;
  adapter_version: string;
  source_mode: string;
  meta: Meta;
}
export interface MapRef extends Ref {
  artifact_id?: string;
}
export interface Overview {
  project: Project;
  maps: MapRef[];
  tasks: Task[];
  unlinked_revisions: Ref[];
  unlinked_runs: Ref[];
  capabilities: Record<string, string>;
}
export interface TaskDetail {
  task: Task;
  briefs: Brief[];
  revisions: Revision[];
  runs: Ref[];
  artifacts: Ref[];
}
export interface RevisionDetail {
  revision: Revision;
  runs: Ref[];
  artifacts: Ref[];
}
export interface Run {
  id: string;
  source_run_id: string;
  kind: string;
  task_revision_id: string | null;
  execution_task_id: string | null;
  preparation: State;
  execution: State;
  acceptance: State;
  stop_reason: string | null;
  phase: string;
  last_activity_at: string | null;
  versions: Record<string, string | null>;
  requirements: Requirement[];
  metrics: Metric[];
  usage: Usage | null;
  attempts: Ref[];
  calls: Ref[];
  artifacts: Ref[];
  report_refs: Ref[];
  meta: Meta;
}
export interface Attempt {
  id: string;
  run_id: string;
  attempt_no: number;
  phase: string;
  execution_state: State;
  outcome: string | null;
  intent: Fact | null;
  rationale: Fact | null;
  execution_summary: Fact | null;
  experiment_summary: Fact | null;
  conclusion: Fact | null;
  gaps: Fact | null;
  next_step: Fact | null;
  parent_commit: string | null;
  candidate_commit: string | null;
  calls: Ref[];
  artifacts: Ref[];
  usage: Usage | null;
  meta: Meta;
}
export interface Call {
  id: string;
  run_id: string | null;
  attempt_id: string | null;
  phase: string;
  role: string;
  provider: string | null;
  provider_call_id: string | null;
  parent_call_id: string | null;
  state: State;
  started_at: string | null;
  ended_at: string | null;
  last_activity_at: string | null;
  transcript_availability: string;
  artifacts: Ref[];
  usage: Usage | null;
  meta: Meta;
}
export interface Artifact {
  content_is_projection?: boolean;
  link_targets?: Record<string, { kind: string; id: string }>;
  id: string;
  kind: string;
  title: string;
  display_path: string;
  content_origin: string;
  owner_refs: Ref[];
  phase: string;
  availability: string;
  mime: string | null;
  size_bytes: number | null;
  digest: string | null;
  digest_algorithm: string | null;
  key_facts: (Fact | string)[];
  can_preview: boolean;
  can_download: boolean;
  meta: Meta;
}
export interface Content {
  artifact_id: string;
  content: string;
  encoding: string;
  byte_offset: number;
  next_offset: number | null;
  eof: boolean;
  truncated: boolean;
  content_version: string;
}
export interface MessageItem {
  id: string;
  role?: string;
  content?: unknown;
  type?: string;
  text?: string;
  [key: string]: unknown;
}
export interface MessagePage {
  call_id: string;
  items: MessageItem[];
  reset: boolean;
  reset_reason: string | null;
}

export interface WorkItem {
  id: string;
  attempt_no: number;
  work_id: string;
  title: string;
  goal: string | null;
  stage: string;
  reason: string | null;
  dependencies: {
    work_id: string;
    attempt_no: number | null;
    title: string | null;
  }[];
  blocked_by: string[];
  calls: string[];
  summary: string | null;
  outcome: string | null;
  needs_attention: boolean;
  availability: string;
}
export interface WorkerSummary {
  progress_summary?: string | null;
  id: string;
  attempt_no: number | null;
  role: string;
  state: string;
  started_at: string | null;
  ended_at: string | null;
  error: string | null;
  activity_available: boolean;
  activity_note: string;
}
export interface Workbench {
  current_progress?: {
    sequence: number;
    at: string | null;
    role: string;
    progress_summary: string;
    attempt_no: number | null;
    call_id: string | null;
  } | null;
  run_brief?: {
    goal: string | null;
    version: string;
    material: Material | null;
  } | null;
  canvas?: {
    cards: CanvasCard[];
    edges: {
      id: string;
      source: string;
      target: string;
      at: string | null;
      sequence: number;
      label: string;
      source_call_id?: string | null;
      target_call_id?: string | null;
    }[];
    rounds: {
      id: string;
      title: string;
      at: string | null;
      attempts: number[];
    }[];
    note: string;
  };
  preparation_materials?: Material[];
  kind?: "preparation" | "execution";
  timeline: {
    id: string;
    title: string;
    at: string | null;
    attempt_no: number | null;
  }[];
  handoffs: {
    id: string;
    source: string;
    target: string;
    attempt_no: number;
    at: string | null;
  }[];
  id: string;
  display_label: string;
  source_run_id: string;
  execution: string;
  goal: string | null;
  stop_reason: string | null;
  result: {
    complete: boolean | null;
    reason: string | null;
    gaps: string | null;
  };
  control: Record<
    "pause" | "resume" | "stop",
    { enabled: boolean; reason: string }
  >;
  control_request: ControlRequestView | null;
  workers: WorkerSummary[];
  workers_truncated: boolean;
  work_count: number;
  availability: string;
  observation_note: string;
}
export interface WorkItemsPage {
  items: WorkItem[];
  total: number;
  scope: string;
}

export interface ToolAction {
  id: string;
  category: string;
  name: string | null;
  object: string | null;
  state: "pending" | "completed" | "failed" | "unconfirmed";
  started_at: string | null;
  ended_at: string | null;
  summary: string | null;
  exit_code: number | null;
}
export interface CallActivity {
  call_id: string;
  actions: ToolAction[];
  availability: string;
  note: string | null;
  reset: boolean;
  truncated: boolean;
  has_more: boolean;
}

export type Material = {
  id: string;
  name: string;
  purpose: string;
  availability: string;
  note: string | null;
};
export type InspectionData = {
  attempt_no: number;
  calls: WorkerSummary[];
  call_id: string | null;
  error: string | null;
  input_note: string;
  input: {
    title: string | null;
    goal: string | null;
    purpose: string | null;
    hypothesis: string | null;
    deliverables: string[];
  } | null;
  output: { summary: string | null; completed: boolean | null } | null;
  materials: Material[];
  material_note?: string;
};

export interface ControlRequestView {
  request_id: string;
  run_id: string;
  action: "pause" | "resume" | "stop";
  status: string;
  sequence: number;
  reason: string;
  run: { state: string; execution_unknown: boolean };
}

export interface CanvasCard {
  id: string;
  role: string;
  kind: string;
  title: string;
  summary: string | null;
  attempt_no: number | null;
  round_id: string | null;
  state: string;
  call_id: string | null;
  material: Material | null;
  at: string | null;
  sequence: number;
  source: { kind: string; sequence: number } | null;
}
