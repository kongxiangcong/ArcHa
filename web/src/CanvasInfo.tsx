import { useRef, useState } from "react";
import type { Workbench, WorkerSummary } from "./types";
import { label, time } from "./components";
export type InfoTab = "task" | "progress" | "worker";
export function CanvasInfo({
  open,
  tab,
  onTab,
  onOpen,
  onClose,
  title,
  scene,
  worker,
}: {
  open: boolean;
  tab: InfoTab;
  onTab: (tab: InfoTab) => void;
  onOpen: () => void;
  onClose: () => void;
  title: string;
  scene?: Workbench;
  worker?: WorkerSummary;
}) {
  const [size, setSize] = useState(() => {
    try {
      return (
        JSON.parse(localStorage.getItem("archa-info-size") ?? "null") ?? {
          width: 350,
          height: 240,
        }
      );
    } catch {
      return { width: 350, height: 240 };
    }
  });
  const start = useRef<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  function close() {
    onClose();
    toggle.current?.focus({ preventScroll: true });
  }
  const copy =
    tab === "task"
      ? [
          title,
          scene?.goal,
          scene?.result.reason,
          scene?.result.gaps,
          scene?.stop_reason,
        ]
          .filter(Boolean)
          .join("\n\n")
      : tab === "worker"
        ? (worker?.progress_summary ?? "暂无该次调用的摘要")
        : (scene?.current_progress?.progress_summary ?? "暂无已记录的进展说明");
  const meta =
    tab === "worker" && worker
      ? `${label(worker.role)} · ${label(worker.state)} · 该次调用自述`
      : tab === "progress" && scene?.current_progress
        ? `最近已完成进展 · ${time(scene.current_progress.at)}`
        : "";
  return (
    <div
      className={`canvas-info${open ? " expanded" : ""}`}
      style={open ? { width: size.width, height: size.height } : undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          close();
        }
      }}
    >
      <button
        ref={toggle}
        className="info-toggle"
        aria-expanded={open}
        onClick={open ? close : onOpen}
      >
        {open ? "收起信息" : "展开信息"}
      </button>
      {open && (
        <>
          <nav aria-label="信息分类">
            {(["task", "progress", "worker"] as const).map((value) => (
              <button
                key={value}
                aria-pressed={tab === value}
                onClick={() => onTab(value)}
              >
                {
                  {
                    task: "任务介绍",
                    progress: "当前进展",
                    worker: "Worker 摘要",
                  }[value]
                }
              </button>
            ))}
          </nav>
          <div
            className="info-copy"
            tabIndex={0}
            aria-live="polite"
            aria-atomic="true"
          >
            {copy.split(/\n\s*\n/).map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
          <small>{meta}</small>
          <button
            className="info-resize"
            aria-label="调整信息窗口大小"
            title="拖动调整大小，或使用方向键"
            onPointerDown={(e) => {
              e.preventDefault();
              e.currentTarget.setPointerCapture(e.pointerId);
              start.current = { x: e.clientX, y: e.clientY, ...size };
            }}
            onPointerMove={(e) => {
              const s = start.current;
              if (!s) return;
              setSize({
                width: Math.max(260, Math.min(600, s.width + s.x - e.clientX)),
                height: Math.max(
                  160,
                  Math.min(500, s.height + e.clientY - s.y),
                ),
              });
            }}
            onPointerUp={() => {
              start.current = null;
              localStorage.setItem("archa-info-size", JSON.stringify(size));
            }}
            onPointerCancel={() => {
              start.current = null;
            }}
            onKeyDown={(e) => {
              if (
                !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
                  e.key,
                )
              )
                return;
              e.preventDefault();
              const next = {
                width: Math.max(
                  260,
                  Math.min(
                    600,
                    size.width +
                      (e.key === "ArrowLeft"
                        ? 20
                        : e.key === "ArrowRight"
                          ? -20
                          : 0),
                  ),
                ),
                height: Math.max(
                  160,
                  Math.min(
                    500,
                    size.height +
                      (e.key === "ArrowDown"
                        ? 20
                        : e.key === "ArrowUp"
                          ? -20
                          : 0),
                  ),
                ),
              };
              setSize(next);
              localStorage.setItem("archa-info-size", JSON.stringify(next));
            }}
          >
            ↙
          </button>
        </>
      )}
    </div>
  );
}
