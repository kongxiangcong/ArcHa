import type { Content, Overview, TopicDetail } from "./types";
const prefix = "/api/observer/v1";
async function read<T>(path: string): Promise<T> {
  const response = await fetch(prefix + path, {
    signal: AbortSignal.timeout(10000),
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(value.error?.message || `HTTP ${response.status}`);
  return value;
}
export const api = {
  topics: () => read<Overview>("/topics"),
  topic: (topic: string) =>
    read<TopicDetail>("/topics/" + encodeURIComponent(topic)),
  material: (path: string, offset = 0) =>
    read<Content>(
      "/materials?" + new URLSearchParams({ path, offset: String(offset) }),
    ),
};
