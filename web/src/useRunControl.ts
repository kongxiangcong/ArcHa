import { useEffect, useRef, useState } from "react";
import { ApiError, controlRequest } from "./api";
import type { ControlRequestView } from "./types";

const pending = (status?: string) =>
  status === "accepted" || status === "processing";

export function useRunControl(run: string, saved?: ControlRequestView | null) {
  const [local, setLocal] = useState<{
    run: string;
    request?: ControlRequestView;
    id?: string;
    sending?: boolean;
    action?: "pause" | "resume" | "stop";
    error?: string;
  }>({ run });
  const intent = useRef<string | undefined>(undefined);
  const target = useRef(run);
  target.current = run;
  const value = local.run === run ? local : { run };
  const progress = (status?: string) =>
    status === "accepted" || status === "unknown"
      ? 0
      : status === "processing"
        ? 1
        : 2;
  const record =
    value.request &&
    (!saved ||
      value.request.sequence > saved.sequence ||
      (value.request.sequence === saved.sequence &&
        progress(value.request.status) > progress(saved.status)))
      ? value.request
      : saved;
  const busy =
    !!value.sending ||
    pending(record?.status) ||
    (!!value.id && record?.request_id !== value.id);
  useEffect(() => {
    if (!value.id || !run) return;
    let active = true;
    const controller = new AbortController();
    async function query() {
      try {
        const result = await controlRequest<ControlRequestView>(
          run,
          value.id!,
          undefined,
          controller.signal,
        );
        if (active)
          setLocal({
            run,
            request: result.data,
            id: pending(result.data.status) ? value.id : undefined,
          });
      } catch (error) {
        if (active && !controller.signal.aborted)
          setLocal((old) => ({
            ...old,
            error: `请求结果尚未确认，正在查询同一次请求。${(error as Error).message}`,
          }));
      }
    }
    void query();
    const timer = setInterval(() => void query(), 1200);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [run, value.id]);

  async function submit(action: "pause" | "resume" | "stop") {
    const interrupt =
      (action === "stop" &&
        (value.sending || pending(record?.status)) &&
        record?.action !== "stop") ||
      (value.action === "resume" && value.sending) ||
      (record?.action === "resume" && pending(record.status));
    if (!run || (busy && !(interrupt && action !== "resume"))) return;
    const id = crypto.randomUUID();
    intent.current = id;
    setLocal({ run, sending: true, action });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const result = await controlRequest<ControlRequestView>(
        run,
        id,
        action,
        controller.signal,
      );
      if (target.current === run && intent.current === id)
        setLocal({
          run,
          request: result.data,
          id: pending(result.data.status) ? id : undefined,
        });
    } catch (error) {
      if (target.current === run && intent.current === id) {
        const rejected = error instanceof ApiError && error.status < 500;
        setLocal({
          run,
          id: rejected ? undefined : id,
          error: rejected
            ? error.message
            : "提交结果尚未确认，先查询同一次请求；不会自动重新提交。",
        });
      }
    } finally {
      clearTimeout(timeout);
    }
  }
  return {
    record,
    busy,
    action: value.action ?? record?.action,
    sending: !!value.sending,
    error: value.error,
    submit,
  };
}
