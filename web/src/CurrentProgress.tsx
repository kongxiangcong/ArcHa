import type { Workbench } from "./types";
import { time, label, preparationLabel } from "./components";

const roles: Record<string, string> = {
  onboard: "研究准备",
  expert: "研究协调",
  designer: "实施",
  reviewer: "独立审核",
  engine: "引擎",
};

export function CurrentProgress({ scene }: { scene?: Workbench }) {
  const progress = scene?.current_progress;
  const pending = scene?.workers.some((worker) => worker.state === "pending");
  return (
    <section
      className="current-progress"
      aria-labelledby="current-progress-title"
    >
      <div className="current-progress-heading">
        <h2 id="current-progress-title">当前进展</h2>
        <span className="muted">
          {scene
            ? scene.kind === "preparation"
              ? "研究准备"
              : "正式运行"
            : "尚未选择准备任务或运行"}
          {scene &&
            ` · ${scene.kind === "preparation" ? preparationLabel(scene.execution) : label(scene.execution)}`}
          {pending && " · 已有调用派发，结束情况以记录为准"}
        </span>
      </div>
      <div
        className="current-progress-copy"
        aria-live="polite"
        aria-atomic="true"
      >
        <p>{progress?.progress_summary ?? "暂无已记录的进展说明"}</p>
      </div>
      {progress && (
        <p className="current-progress-meta">
          最近已完成进展 · {roles[progress.role] ?? "引擎"} · 更新于{" "}
          {time(progress.at)}
        </p>
      )}
    </section>
  );
}
