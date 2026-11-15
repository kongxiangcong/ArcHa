export type Activity = "idle" | "running" | "stopping" | "unknown";
export type Role = "expert" | "executor" | "expert_finalize";
export type Material = { name: string; path: string };
export type Topic = {
  topic: string;
  status?: string;
  max_rounds?: number;
  completed_rounds?: number;
  current_round?: number;
  next_action?: string;
  activity?: Activity;
  publishing?: boolean;
  debug_probes?: boolean;
  probe_breakpoint?: boolean;
  execution?: {
    id: string;
    role: Role;
    round: number;
    started_at: string;
  } | null;
  error?: string;
};
export type Round = {
  number: number;
  completed: boolean;
  materials: Material[];
  logs: (Material & { role: Role })[];
};
export type TopicDetail = Topic & {
  current_probe?: Material | null;
  rounds: Round[];
  materials: Material[];
};
export type Overview = {
  project: string;
  demo: boolean;
  control: boolean;
  topics: Topic[];
};
export type Content = {
  path: string;
  text: string;
  offset: number;
  next_offset: number;
  more: boolean;
};
