import type { Content, Overview, TopicDetail, Topic, Role, EventBatch } from "./types";
const prefix = "/api/observer/v1";
async function read<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(prefix + path, {
    signal: AbortSignal.timeout(20000),
    ...(body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(value.error?.message || `HTTP ${response.status}`);
  return value;
}
export const api = {
  events: (topic: string, step: number, role: Role, after_seq = 0, stream: string | null = null) =>
    read<EventBatch>(`/topics/${encodeURIComponent(topic)}/steps/${step}/events?` +
      new URLSearchParams({role, after_seq: String(after_seq), ...(stream === null ? {} : {stream})})),
  resume: (topic: string, add_rounds?: number, debug_probes?: boolean) =>
    read<{ accepted: boolean }>(
      "/topics/" + encodeURIComponent(topic) + "/resume",
      { add_rounds, debug_probes },
    ),
  revise: (topic: string, feedback: string) =>
    read<{ accepted: boolean }>(
      "/topics/" + encodeURIComponent(topic) + "/revise",
      { feedback },
    ),
  stop: (topic: string, execution_id: string) =>
    read<Topic>("/topics/" + encodeURIComponent(topic) + "/stop", {
      execution_id,
    }),
  topics: () => read<Overview>("/topics"),
  topic: (topic: string) =>
    read<TopicDetail>("/topics/" + encodeURIComponent(topic)),
  material: (path: string, offset = 0) =>
    read<Content>(
      "/materials?" + new URLSearchParams({ path, offset: String(offset) }),
    ),
};
