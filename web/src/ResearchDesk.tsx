import { useEffect, useRef, useState } from "react";
import type { Workbench, Material } from "./types";
import { label, time, preparationLabel } from "./components";

const modules = [
  { role: "onboard", title: "研究准备", description: "接入评价与准备研究条件" },
  { role: "expert", title: "研究协调", description: "提出方向与解释反馈" },
  { role: "designer", title: "实施", description: "形成工作与研究产出" },
  { role: "evaluator", title: "评价", description: "检查实际结果" },
  { role: "reviewer", title: "独立审核", description: "按合同核对交付" },
];

/** Saved lifecycle facts drive the stage; there is no simulated agent activity. */
export function ResearchDesk({
  scene,
  hidden,
  onChoose,
  onOpen,
}: {
  scene?: Workbench;
  hidden: boolean;
  onChoose: (attempt: number) => void;
  onOpen: (material: Material, opener: HTMLElement) => void;
}) {
  const seen = useRef<Set<string> | null>(null);
  const [pulses, setPulses] = useState<string[]>([]);
  const [history, setHistory] = useState(false);
  const handoffs = scene?.handoffs ?? [];
  const signature = handoffs.map((item) => item.id).join("|");
  const latest = scene?.timeline.at(-1);
  const previous = useRef<string | undefined>(undefined);
  const [arrived, setArrived] = useState(false);
  useEffect(() => {
    const changed =
      previous.current !== undefined && latest?.id !== previous.current;
    previous.current = latest?.id;
    setArrived(changed);
    const timer = setTimeout(() => setArrived(false), 650);
    return () => clearTimeout(timer);
  }, [latest?.id]);
  useEffect(() => {
    if (!scene) return;
    const current = new Set(handoffs.map((item) => item.id));
    const fresh = seen.current
      ? [...current].filter((id) => !seen.current!.has(id))
      : [];
    seen.current = current;
    setPulses(fresh);
    const timer = setTimeout(() => setPulses([]), 650);
    return () => clearTimeout(timer);
  }, [signature, !!scene]);
  const pending =
    scene?.workers.filter((worker) => worker.state === "pending") ?? [];
  return (
    <section className="research-desk" hidden={hidden} aria-label="议题研究桌">
      <div className="desk-heading">
        <span className="eyebrow">
          {scene?.kind === "preparation"
            ? "研究准备现场 · 尚未启动正式运行"
            : "研究现场"}
        </span>
        <button
          className="link-button"
          aria-expanded={history}
          onClick={() => setHistory(!history)}
        >
          {history ? "返回当前现场" : "回看演进"}
        </button>
      </div>
      <div className="research-stage">
        <div className="stage-focus">
          <p className="stage-kicker">
            {scene
              ? scene.kind === "preparation"
                ? preparationLabel(scene.execution)
                : label(scene.execution)
              : "等待选择运行"}{" "}
            ·{" "}
            {pending.length
              ? `${pending.length} 次调用尚待结果`
              : scene?.kind === "preparation"
                ? "已保存准备状态；当前调用活动未确认"
                : "当前没有待结果调用"}
          </p>
          <h2>{scene?.goal ?? "从一个议题，走进正在发生的研究。"}</h2>
          <div
            className={`latest-change${arrived ? " arrived" : ""}`}
            aria-live="polite"
            aria-atomic="true"
          >
            {latest ? (
              <>
                <span className="change-mark" aria-hidden="true" />
                <span>{latest.title}</span>
                <time>{time(latest.at)}</time>
                {latest.attempt_no && (
                  <button
                    className="link-button"
                    onClick={() => onChoose(latest.attempt_no!)}
                  >
                    进入工作 {latest.attempt_no}
                  </button>
                )}
              </>
            ) : (
              "选中运行后，真实进展会在这里出现。"
            )}
          </div>
          {scene?.result.reason && (
            <p className="stage-result">
              {scene.result.complete === true ? "交付完成" : "当前判断"} ·{" "}
              {scene.result.reason}
            </p>
          )}
        </div>
        <div className="module-presence" aria-label="研究模块状态">
          {modules.map((module) => {
            const calls =
              scene?.workers.filter((worker) => worker.role === module.role) ??
              [];
            const waiting = calls.filter(
              (worker) => worker.state === "pending",
            );
            const latestCall = calls.at(-1);
            const state = waiting.length
              ? "pending"
              : (latestCall?.state ?? "absent");
            return (
              <div
                className={`module-state ${state}`}
                key={module.role}
                data-module={module.role}
              >
                <span className="module-mark" aria-hidden="true" />
                <div>
                  <strong>{module.title}</strong>
                  <small>{module.description}</small>
                </div>
                <span className="module-fact" key={state + ":" + calls.length}>
                  {waiting.length
                    ? `${waiting.length} 次已派发 · 结果待确认`
                    : latestCall
                      ? label(latestCall.state)
                      : scene?.kind === "preparation" &&
                          module.role === "onboard"
                        ? "调用活动归属未登记"
                        : "暂无调用"}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="handoff-strip" aria-label="已记录的成果交接">
        {handoffs.slice(-3).map((item) => (
          <button
            key={item.id}
            className={`handoff-card${pulses.includes(item.id) ? " activated" : ""}`}
            onClick={() => onChoose(item.attempt_no)}
          >
            <span>{item.source}</span>
            <span className="handoff-path" aria-hidden="true">
              →
            </span>
            <span>{item.target}</span>
            <small>{time(item.at)} · 输入交接</small>
          </button>
        ))}
        {!handoffs.length && (
          <span className="muted">
            工作与成果各有位置。实际交接发生时，相关工作会在这里连起一次。
          </span>
        )}
      </div>
      {scene?.preparation_materials?.length ? (
        <div className="prepared-materials">
          <strong>准备材料</strong>
          {scene.preparation_materials.map((material) => (
            <button
              key={material.id}
              className="link-button"
              onClick={(event) => onOpen(material, event.currentTarget)}
            >
              {material.name}
            </button>
          ))}
        </div>
      ) : null}
      {history && (
        <ol className="evolution t-panel-reveal" aria-label="研究演进记录">
          {scene?.timeline.map((item) => (
            <li key={item.id}>
              <time>{time(item.at)}</time>{" "}
              {item.attempt_no ? (
                <button
                  className="link-button"
                  onClick={() => onChoose(item.attempt_no!)}
                >
                  {item.title} · 工作 {item.attempt_no}
                </button>
              ) : (
                item.title
              )}
            </li>
          ))}
          <li className="muted">
            最近 100 项已记录变化；回看不会重新执行研究。
          </li>
        </ol>
      )}
    </section>
  );
}
