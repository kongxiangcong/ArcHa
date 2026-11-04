import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { enc, get } from "./api";
type Log = {
  content: string;
  path: string | null;
  added: number;
  can_update: boolean;
  reason?: string;
};
export function ResearchLog({
  run,
  onClose,
}: {
  run: string;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const copy = useRef<HTMLDivElement>(null);
  const [log, setLog] = useState<Log>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("读取日志中…");
  const started = useRef(false);
  const alive = useRef(true);
  function close() {
    dialog.current?.close();
    onClose();
  }
  async function update() {
    setBusy(true);
    setError("");
    setMessage("正在整理新增进展…");
    try {
      const response = await fetch(
        `/api/control/v1/runs/${enc(run)}/research-log`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          }),
        },
      );
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message ?? "日志更新失败");
      if (!alive.current) return;
      setLog(body.data);
      setMessage(
        body.data.added
          ? `已追加 ${body.data.added} 条记录`
          : "没有新的研究进展，日志未改动",
      );
      if (body.data.added)
        requestAnimationFrame(() =>
          copy.current?.lastElementChild?.scrollIntoView({ block: "end" }),
        );
    } catch (e) {
      if (alive.current) {
        setError(String(e));
        setMessage("更新失败，已有日志保留");
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    dialog.current?.showModal();
    if (!started.current) {
      started.current = true;
      void get<Log>(`/runs/${enc(run)}/research-log`)
        .then((result) => {
          if (!alive.current) return;
          setLog(result.data);
          if (result.data.can_update) void update();
          else setMessage(result.data.reason ?? "只读模式：展示已有日志");
        })
        .catch((e) => {
          if (alive.current) {
            setError(String(e));
            setMessage("读取失败");
          }
        });
    }
    return () => {
      alive.current = false;
    };
  }, [run]);
  return (
    <dialog
      className="research-log-dialog"
      ref={dialog}
      aria-labelledby="research-log-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <header>
        <h2 id="research-log-title">研究日志</h2>
        <button
          className="btn"
          disabled={busy || !log?.can_update}
          onClick={() => void update()}
        >
          {busy ? "更新中…" : "更新日志"}
        </button>
        <button className="btn" onClick={close}>
          关闭日志
        </button>
      </header>
      <p role="status">{message}</p>
      {error && <p role="alert">{error}</p>}
      <div className="research-log-copy" ref={copy} tabIndex={0}>
        <ReactMarkdown skipHtml>
          {log?.content || "暂无已记录的研究日志"}
        </ReactMarkdown>
      </div>
      {log?.path && <small>{log.path}</small>}
    </dialog>
  );
}
