import { useEffect, useRef, useState } from "react";
import { ThinkingOrb } from "thinking-orbs";
import { poll } from "./poll";
import { enc, get } from "./api";
import { time } from "./components";
import type { CallActivity, WorkerSummary } from "./types";

export function Activity({
  worker,
  expanded = false,
}: {
  worker: WorkerSummary;
  expanded?: boolean;
}) {
  const root = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(expanded);
  const [state, setState] = useState<{
    id: string;
    value?: CallActivity;
    error?: string;
  }>({ id: worker.id });
  useEffect(() => {
    if (expanded) {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) =>
      setVisible(entry.isIntersecting),
    );
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, [expanded]);
  useEffect(() => {
    if (!visible || !worker.activity_available) return;
    let active = true,
      pending = false,
      cursor: string | null = null;
    const controller = new AbortController();
    async function read() {
      if (pending) return;
      pending = true;
      try {
        let more = false;
        do {
          const page = await get<CallActivity>(
            `/calls/${enc(worker.id)}/activity${cursor ? "?cursor=" + enc(cursor) : ""}`,
            controller.signal,
          );
          if (!active) break;
          cursor = page.next_cursor;
          more = page.data.has_more;
          setState({ id: worker.id, value: page.data });
          // Yield between bounded pages so a large terminal tail cannot freeze navigation.
          if (more)
            await new Promise<void>((resolve) => setTimeout(resolve, 0));
        } while (more && active);
      } catch (error) {
        if (active && !controller.signal.aborted)
          setState((old) => ({ ...old, error: (error as Error).message }));
      } finally {
        pending = false;
      }
    }
    const stop = poll(read, worker.state === "pending" ? 1000 : 0);
    return () => {
      active = false;
      controller.abort();
      stop();
    };
  }, [worker.id, worker.state, worker.activity_available, visible]);
  const value = state.id === worker.id ? state.value : undefined;
  const actions = expanded ? value?.actions : value?.actions.slice(-1);
  const observedBusy =
    worker.state === "pending" &&
    !state.error &&
    value?.actions.some((action) => {
      const at = Date.parse(action.started_at ?? "");
      return (
        action.state === "pending" &&
        Number.isFinite(at) &&
        Date.now() - at < 15000
      );
    });
  const pendingCount =
    value?.actions.filter((a) => a.state === "pending").length ?? 0;
  return (
    <span className={`activity ${expanded ? "expanded" : ""}`} ref={root}>
      {observedBusy && visible && (
        <ThinkingOrb
          state="working"
          size={20}
          aria-label="最近观察到工具动作，结果待确认"
        />
      )}
      {state.error && (
        <span className="activity-warning">
          活动更新失败，保留最后记录：{state.error}
        </span>
      )}
      {value?.reset && (
        <span className="activity-warning">
          日志已替换或截断，重新显示可确认的活动。
        </span>
      )}
      {actions?.map((action) => (
        <span className="tool-action" key={action.id}>
          <span className="tool-action-title">
            {action.category === "command"
              ? "执行命令"
              : action.category === "file"
                ? "文件操作"
                : action.name}{" "}
            ·{" "}
            {action.state === "pending"
              ? "已开始，结果待确认"
              : action.state === "unconfirmed"
                ? "调用已结束，动作结果未确认"
                : action.state === "failed"
                  ? "动作失败"
                  : "动作完成"}
          </span>
          {action.object && <code>{action.object}</code>}
          {expanded && action.summary && (
            <span className="tool-summary">{action.summary}</span>
          )}
          {expanded && action.exit_code !== null && (
            <span>退出码 {action.exit_code}</span>
          )}
          <span className="activity-time">
            {action.ended_at || action.started_at
              ? time(action.ended_at ?? action.started_at)
              : "未提供动作时间"}
          </span>
        </span>
      ))}
      {!actions?.length && (
        <span className="activity-line">
          {value?.note ?? worker.activity_note}
        </span>
      )}
      {!expanded && pendingCount > 0 && (
        <span className="activity-line">
          {pendingCount} 个动作结果待确认；选择查看
        </span>
      )}
      {value?.truncated && (
        <span className="activity-line">
          显示有界最近活动，较早动作可能不完整。
        </span>
      )}
    </span>
  );
}
