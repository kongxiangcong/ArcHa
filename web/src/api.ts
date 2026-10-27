import { useEffect, useState } from "react";
import type { Envelope } from "./types";
export const base = "/api/observer/v1";
export const enc = encodeURIComponent;
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
  }
}
export async function get<T>(
  path: string,
  signal?: AbortSignal,
): Promise<Envelope<T>> {
  const response = await fetch(base + path, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.message || `读取失败 (${response.status})`,
      response.status,
      body?.error?.code ?? "http_error",
    );
  }
  const body = await response.json();
  if (!String(body.schema_version).startsWith("1."))
    throw new Error("观察接口主版本不兼容");
  return body;
}
export function useResource<T>(path: string | null, interval = 0, refresh = 0) {
  const [state, setState] = useState<{
    path: string | null;
    value?: Envelope<T>;
    error?: string;
  }>({ path: null });
  useEffect(() => {
    if (!path) return;
    let active = true,
      pending = false;
    const ctrl = new AbortController();
    const read = async () => {
      if (pending) return;
      pending = true;
      try {
        const value = await get<T>(path, ctrl.signal);
        if (active) setState({ path, value });
      } catch (e) {
        if (active && !ctrl.signal.aborted)
          setState((old) => ({
            path,
            value: old.path === path ? old.value : undefined,
            error: String((e as Error).message),
          }));
      } finally {
        pending = false;
      }
    };
    void read();
    const timer = interval
      ? setInterval(() => void read(), interval)
      : undefined;
    return () => {
      active = false;
      ctrl.abort();
      clearInterval(timer);
    };
  }, [path, interval, refresh]);
  return state.path === path
    ? state
    : { path, value: undefined, error: undefined };
}
