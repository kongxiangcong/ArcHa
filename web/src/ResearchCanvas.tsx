import { useEffect, useRef, useState } from "react";
import dagre from "@dagrejs/dagre";
import type {
  ReactNode,
  CSSProperties,
  PointerEvent as ReactPointerEvent,
} from "react";
import type {
  CanvasCard,
  Material,
  TaskDetail,
  Workbench,
  WorkerSummary,
} from "./types";
import { label, time } from "./components";
import { Activity } from "./Activity";
import "./canvas.css";

type Camera = { x: number; y: number; scale: number };
const colors: Record<string, string> = {
  human: "#c9cec4",
  context: "#c9cec4",
  system: "#d8b28b",
  onboard: "#92b8a5",
  expert: "#b6abd9",
  designer: "#9db9d8",
  evaluator: "#d8b28b",
  reviewer: "#d3bb8b",
};
const finiteTime = (value: string | null) => {
  const n = Date.parse(value ?? "");
  return Number.isFinite(n) ? n : null;
};

/** One coordinate owner for cards and SVG; no inferred communication or simulated playback. */
export function ResearchCanvas({
  scene,
  task,
  scope,
  hidden,
  selectedNo,
  selectedCall,
  onWork,
  onWorker,
  onOpen,
  onInspect,
  onFollow,
  onFactOpen,
  infoPanel,
  infoOpen,
}: {
  infoPanel?: ReactNode;
  infoOpen?: boolean;
  scene?: Workbench;
  task?: TaskDetail;
  scope: string;
  hidden: boolean;
  selectedNo: number | null;
  selectedCall: string | null;
  onWork: (number: number, opener: HTMLElement) => void;
  onWorker: (worker: WorkerSummary, opener: HTMLElement) => void;
  onOpen: (material: Material, opener: HTMLElement) => void;
  onInspect: () => void;
  onFollow: () => void;
  onFactOpen: () => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const saved = useRef<{
    camera?: Camera;
    following?: boolean;
    folded?: string[];
  } | null>(null);
  if (saved.current === null) {
    try {
      saved.current = JSON.parse(
        sessionStorage.getItem("archa-canvas:" + scope) ?? "{}",
      );
    } catch {
      saved.current = {};
    }
  }
  const [camera, setCamera] = useState<Camera>(
    saved.current?.camera ?? { x: 24, y: 12, scale: 0.82 },
  );
  const [following, setFollowing] = useState(saved.current?.following ?? true);
  const [folded, setFolded] = useState<string[]>(saved.current?.folded ?? []);
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [factId, setFactId] = useState<string | null>(null);
  useEffect(() => {
    if (infoOpen) setFactId(null);
  }, [infoOpen]);
  const factHeading = useRef<HTMLHeadingElement>(null);
  const factOpener = useRef<HTMLElement | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pulses, setPulses] = useState<string[]>([]);
  const [arrivals, setArrivals] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [size, setSize] = useState({ width: 1000, height: 500 });
  const [osReduced, setOsReduced] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [manualReduced, setManualReduced] = useState(false);
  const [visible, setVisible] = useState(!document.hidden);
  const reduced = osReduced || manualReduced;
  const observed = useRef<{ cards: Set<string>; edges: Set<string> } | null>(
    null,
  );
  const initial = useRef(false);
  const suppressClick = useRef(false);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const drag = useRef<{
    x: number;
    y: number;
    camera: Camera;
    distance?: number;
  } | null>(null);
  const graph = scene?.canvas;
  const cards: CanvasCard[] = [...(graph?.cards ?? [])];
  // Historical runs use their frozen contract binding, never task.briefs[0].
  if (scene && scene.kind !== "preparation")
    cards.unshift({
      id: "brief:" + scope,
      role: "context",
      kind: "brief",
      title: "研究约定",
      summary: scene.run_brief?.goal ?? scene.goal ?? "本次运行目标未记录",
      attempt_no: null,
      round_id: null,
      call_id: null,
      state: "recorded",
      at: null,
      sequence: 0,
      source: null,
      material: scene.run_brief?.material ?? null,
    });
  // Layout follows recorded dependencies; display coordinates never create handoffs.
  const layout = new dagre.graphlib.Graph();
  layout.setGraph({
    rankdir: "LR",
    ranksep: 55,
    nodesep: 55,
    marginx: 50,
    marginy: 130,
  });
  layout.setDefaultEdgeLabel(() => ({}));
  for (const card of cards)
    layout.setNode(card.id, { width: 245, height: 230 });
  for (const edge of graph?.edges ?? []) {
    if (layout.hasNode(edge.source) && layout.hasNode(edge.target))
      layout.setEdge(edge.source, edge.target);
  }
  // Keep recorded stages of a work readable even when no handoff was recorded.
  // These ordering constraints belong only to the layout, never the displayed edges.
  for (const no of new Set(cards.map((card) => card.attempt_no))) {
    if (no === null) continue;
    let previous: CanvasCard[] = [];
    for (const kind of [
      "direction",
      "implementation",
      "artifact",
      "evaluation",
      "feedback",
    ]) {
      const stage = cards.filter(
        (card) => card.attempt_no === no && card.kind === kind,
      );
      if (!stage.length) continue;
      for (const from of previous)
        for (const to of stage) layout.setEdge(from.id, to.id);
      previous = stage;
    }
  }
  dagre.layout(layout);
  const points = new Map(
    cards.map((card) => {
      const point = layout.node(card.id);
      return [card.id, { x: point.x - 122.5, y: point.y - 115 }];
    }),
  );
  const fact = cards.find((card) => card.id === factId);
  const shown = cards.filter(
    (card) => !card.round_id || !folded.includes(card.round_id),
  );
  const edges = (graph?.edges ?? []).filter(
    (edge) =>
      shown.some((c) => c.id === edge.source) &&
      shown.some((c) => c.id === edge.target),
  );
  const latest = cards.reduce<CanvasCard | undefined>(
    (last, card) => (!last || card.sequence >= last.sequence ? card : last),
    undefined,
  );
  const live =
    scene?.execution === "active" ||
    (scene?.kind === "preparation" && scene.execution === "pending");

  function inspect() {
    setFollowing(false);
    onInspect();
  }
  function focus(card: CanvasCard, scale = camera.scale) {
    const p = points.get(card.id);
    if (!p) return;
    const panelWidth = infoOpen
      ? (viewport.current
          ?.querySelector(".canvas-info")
          ?.getBoundingClientRect().width ?? 350) + 24
      : 0;
    const width =
      size.width - panelWidth > 270 ? size.width - panelWidth : size.width;
    scale = Math.min(scale, (width - 32) / 245, (size.height - 32) / 230);
    setCamera({
      x: Math.max(22, width * 0.47 - 122 * scale) - p.x * scale,
      y: Math.max(12, (size.height - 230 * scale) / 2) - p.y * scale,
      scale,
    });
  }
  useEffect(() => {
    if (infoOpen) {
      const card = cards.find((c) => c.id === selected);
      if (card) focus(card);
    }
  }, [infoOpen]);
  function select(card: CanvasCard, opener: HTMLElement, locate = false) {
    inspect();
    setSelected(card.id);
    if (card.round_id)
      setFolded((old) => old.filter((id) => id !== card.round_id));
    if (locate || card.call_id) focus(card);
    const selectedWorker = scene?.workers.find(
      (item) => item.id === card.call_id,
    );
    if (
      selectedWorker &&
      ["expert", "designer", "onboard", "reviewer"].includes(card.role)
    ) {
      setFactId(null);
      onWorker(selectedWorker, opener);
    } else if (
      ["expert", "designer"].includes(card.role) &&
      card.attempt_no !== null
    ) {
      setFactId(null);
      onWork(card.attempt_no, opener);
    } else if (card.material?.availability === "available") {
      setFactId(null);
      onOpen(card.material, opener);
    } else if (
      card.kind === "feedback" ||
      card.kind === "brief" ||
      (!card.call_id && !card.attempt_no)
    ) {
      factOpener.current = opener;
      onFactOpen();
      setFactId(card.id);
    } else {
      setFactId(null);
      const worker = scene?.workers.find((item) => item.id === card.call_id);
      if (worker) onWorker(worker, opener);
      else if (card.attempt_no !== null) onWork(card.attempt_no, opener);
    }
  }
  useEffect(() => {
    if (factId) factHeading.current?.focus({ preventScroll: true });
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape" && factId) {
        event.preventDefault();
        setFactId(null);
        factOpener.current?.focus({ preventScroll: true });
      }
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, [factId]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const resize = new ResizeObserver(([entry]) =>
      setSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    resize.observe(element);
    return () => resize.disconnect();
  }, []);
  useEffect(() => {
    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const motion = () => setOsReduced(query.matches);
    const visibility = () => setVisible(!document.hidden);
    query.addEventListener("change", motion);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      query.removeEventListener("change", motion);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  useEffect(() => {
    sessionStorage.setItem(
      "archa-canvas:" + scope,
      JSON.stringify({ camera, following, folded }),
    );
  }, [scope, camera, following, folded]);
  useEffect(() => {
    if (!scene || !cards.length || initial.current) return;
    initial.current = true;
    if (!saved.current?.camera && latest)
      focus(latest, size.width < 700 ? 0.85 : 0.82);
  }, [!!scene, size.width, cards.length]);
  const signature =
    (graph?.cards ?? []).map((c) => c.id).join("|") +
    ":" +
    (graph?.edges ?? []).map((e) => e.id).join("|");
  useEffect(() => {
    if (!graph) return;
    const next = {
      cards: new Set(graph.cards.map((c) => c.id)),
      edges: new Set(graph.edges.map((e) => e.id)),
    };
    const old = observed.current;
    observed.current = next;
    if (!old || !live || !visible || reduced) return;
    const fresh = [...next.cards].filter((id) => !old.cards.has(id));
    setArrivals(fresh);
    setPulses([...next.edges].filter((id) => !old.edges.has(id)));
    if (following && fresh.length && latest) focus(latest);
    const timeout = setTimeout(() => {
      setArrivals([]);
      setPulses([]);
    }, 1400);
    return () => clearTimeout(timeout);
  }, [signature]);
  useEffect(() => {
    if (selectedCall) {
      const card = cards.find((c) => c.call_id === selectedCall);
      if (card) {
        setSelected(card.id);
        if (card.round_id)
          setFolded((old) => old.filter((id) => id !== card.round_id));
      }
    } else if (selectedNo) {
      const card = cards.find((c) => c.attempt_no === selectedNo);
      if (card) setSelected(card.id);
    }
  }, [selectedNo, selectedCall]);
  function zoom(factor: number) {
    inspect();
    const scale = Math.min(1.6, Math.max(0.1, camera.scale * factor));
    setCamera({
      x: size.width / 2 - ((size.width / 2 - camera.x) * scale) / camera.scale,
      y:
        size.height / 2 - ((size.height / 2 - camera.y) * scale) / camera.scale,
      scale,
    });
  }
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      if ((event.target as HTMLElement).closest(".canvas-info")) return;
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      zoom(event.deltaY > 0 ? 0.93 : 1.07);
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [camera, size, onInspect]);
  function start(event: ReactPointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest(".canvas-info")) return;
    if (event.button !== 0) return;
    const control = (event.target as HTMLElement).closest("button,a,select");
    if (control && !control.matches(".cc-card")) return;
    suppressClick.current = false;
    pointers.current.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    });
    const values = [...pointers.current.values()];
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      camera,
      distance:
        values.length === 2
          ? Math.hypot(values[0].x - values[1].x, values[0].y - values[1].y)
          : undefined,
    };
  }
  function move(event: ReactPointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(event.pointerId) || !drag.current) return;
    pointers.current.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    });
    const d = drag.current,
      values = [...pointers.current.values()];
    if (values.length === 2 && d.distance) {
      suppressClick.current = true;
      setDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId);
      inspect();
      const scale = Math.min(
        1.6,
        Math.max(
          0.1,
          (d.camera.scale *
            Math.hypot(values[0].x - values[1].x, values[0].y - values[1].y)) /
            d.distance,
        ),
      );
      setCamera({
        x:
          size.width / 2 -
          ((size.width / 2 - d.camera.x) * scale) / d.camera.scale,
        y:
          size.height / 2 -
          ((size.height / 2 - d.camera.y) * scale) / d.camera.scale,
        scale,
      });
    } else if (
      Math.abs(event.clientX - d.x) + Math.abs(event.clientY - d.y) >
      4
    ) {
      suppressClick.current = true;
      setDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId);
      inspect();
      setCamera({
        ...d.camera,
        x: d.camera.x + event.clientX - d.x,
        y: d.camera.y + event.clientY - d.y,
      });
    }
  }
  function end(event: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    drag.current = null;
    setDragging(false);
  }
  const selectedNode = cards.find((card) => card.id === selected);
  const activeTimelineCall = selectedNode ? selectedNode.call_id : selectedCall;
  const known = (scene?.workers ?? []).flatMap((w) => {
    const start = finiteTime(w.started_at),
      end = finiteTime(w.ended_at);
    return start === null
      ? []
      : end !== null && end >= start
        ? [start, end]
        : [start];
  });
  const min = known.length ? Math.min(...known) : 0,
    max = known.length ? Math.max(...known) : 1,
    extent = Math.max(max - min, 1000);
  const roles = [...new Set(scene?.workers.map((w) => w.role) ?? [])];
  const timelineWorkers = scene?.workers ?? [];
  const overallWorkers = timelineWorkers.filter(
    (worker) => worker.role === "expert" || worker.role === "designer",
  );
  const laneEnds: number[] = [];
  const overallSpans = overallWorkers
    .filter((worker) => finiteTime(worker.started_at) !== null)
    .sort((a, b) => finiteTime(a.started_at)! - finiteTime(b.started_at)!)
    .map((worker) => {
      const start = finiteTime(worker.started_at)!;
      const end = Math.max(
        finiteTime(worker.ended_at) ?? start,
        start + extent * 0.005,
      );
      let lane = laneEnds.findIndex((until) => until <= start);
      if (lane < 0) lane = laneEnds.length;
      laneEnds[lane] = end;
      return { worker, lane };
    });
  const overallUnknown = overallWorkers.filter(
    (worker) => finiteTime(worker.started_at) === null,
  );
  const overallHeight = overallWorkers.length
    ? Math.max(29, laneEnds.length * 22 + 4) + (overallUnknown.length ? 29 : 0)
    : 29;
  function chooseTimelineWorker(worker: WorkerSummary, opener: HTMLElement) {
    inspect();
    setFactId(null);
    const card = cards.find((c) => c.call_id === worker.id);
    if (card) {
      setSelected(card.id);
      if (card.round_id)
        setFolded((old) => old.filter((id) => id !== card.round_id));
      focus(card, size.width < 700 ? 0.87 : 0.82);
    }
    onWorker(worker, opener);
  }
  function timelineSpan(worker: WorkerSummary, overall = false, lane = 0) {
    const start = finiteTime(worker.started_at),
      end = finiteTime(worker.ended_at);
    if (start === null)
      return (
        <button
          key={worker.id}
          className="cc-unknown-time"
          onClick={(e) => chooseTimelineWorker(worker, e.currentTarget)}
        >
          {label(worker.role)} · 时间未记录 · {label(worker.state)}
        </button>
      );
    const width =
      end !== null && end >= start
        ? Math.max(0.5, ((end - start) / extent) * 98)
        : 0.5;
    return (
      <button
        key={worker.id}
        className={`cc-span${activeTimelineCall === worker.id ? " selected" : ""}`}
        style={
          {
            left: `${((start - min) / extent) * 98}%`,
            width: `${width}%`,
            top: overall ? lane * 22 + 1 : 1,
            "--role": colors[worker.role] ?? colors.expert,
          } as CSSProperties
        }
        title={`${label(worker.role)} · ${label(worker.state)} · ${time(worker.started_at)}${worker.ended_at ? " → " + time(worker.ended_at) : " · 结束时间未记录"}`}
        aria-label={`${label(worker.role)} ${worker.attempt_no ? "工作 " + worker.attempt_no : "运行级调用"} ${label(worker.state)}`}
        onClick={(e) => chooseTimelineWorker(worker, e.currentTarget)}
      >
        {overall ? `${label(worker.role)} · ` : ""}
        {worker.attempt_no ? "工作 " + worker.attempt_no : label(worker.state)}
      </button>
    );
  }
  const timelineLinks = (graph?.edges ?? []).flatMap((edge) => {
    const a = timelineWorkers.findIndex((w) => w.id === edge.source_call_id),
      b = timelineWorkers.findIndex((w) => w.id === edge.target_call_id),
      at = finiteTime(edge.at);
    return edge.label === "传入任务材料" &&
      a >= 0 &&
      b >= 0 &&
      a !== b &&
      at !== null &&
      known.length &&
      at >= min &&
      at <= max
      ? [{ edge, a, b, x: ((at - min) / extent) * 980 }]
      : [];
  });
  const worldWidth = Math.max(
    1600,
    ...[...points.values()].map((p) => p.x + 280),
  );
  const worldHeight = Math.max(
    620,
    ...[...points.values()].map((p) => p.y + 250),
  );
  function path(source: string, target: string) {
    const a = points.get(source)!,
      b = points.get(target)!;
    if (b.y >= a.y + 230 || a.y >= b.y + 230) {
      const downward = b.y > a.y;
      const fromY = a.y + (downward ? 230 : 0);
      const toY = b.y + (downward ? 0 : 230);
      const middle = (fromY + toY) / 2;
      return `M ${a.x + 122.5} ${fromY} C ${a.x + 122.5} ${middle},${b.x + 122.5} ${middle},${b.x + 122.5} ${toY}`;
    }
    return `M ${a.x + 245} ${a.y + 115} C ${a.x + 272.5} ${a.y + 115},${b.x - 27.5} ${b.y + 115},${b.x} ${b.y + 115}`;
  }
  return (
    <section
      className={`research-canvas${reduced ? " reduced" : ""}${!visible ? " backgrounded" : ""}`}
      hidden={hidden}
      aria-label="研究画布"
    >
      <div className="canvas-modules" aria-label="研究模块状态">
        {roles.map((role) => {
          const workers = scene?.workers.filter((w) => w.role === role) ?? [];
          const pending = workers.filter((w) => w.state === "pending");
          return (
            <span
              key={role}
              style={
                { "--role": colors[role] ?? colors.expert } as CSSProperties
              }
            >
              {label(role)}{" "}
              <strong>
                {pending.length
                  ? `${pending.length} 次结果待确认`
                  : label(workers.at(-1)?.state ?? "unknown")}
              </strong>
            </span>
          );
        })}
        {scene?.kind === "preparation" && !roles.length && (
          <span>研究准备 · 调用活动归属未登记</span>
        )}
      </div>
      <div
        ref={viewport}
        className="cc-viewport"
        aria-label="研究画布视口"
        title="拖动平移；上下滚动浏览；Ctrl 或 ⌘ 加滚轮缩放"
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        onClickCapture={(event) => {
          if (suppressClick.current && event.detail !== 0) {
            event.preventDefault();
            event.stopPropagation();
          }
          suppressClick.current = false;
        }}
        onDragStart={(event) => event.preventDefault()}
      >
        {infoPanel}
        <div
          className={`cc-world${dragging ? " dragging" : ""}`}
          data-camera={`${camera.x},${camera.y},${camera.scale}`}
          style={{
            width: worldWidth,
            height: worldHeight,
            transform: `translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`,
          }}
        >
          <svg
            className="cc-edges"
            width={worldWidth}
            height={worldHeight}
            aria-hidden="true"
          >
            {edges.map((edge) => (
              <g key={edge.id}>
                <path className="cc-edge" d={path(edge.source, edge.target)} />
                <path
                  data-handoff={edge.id}
                  className={`cc-edge${pulses.includes(edge.id) ? " flash" : ""}`}
                  style={{ opacity: pulses.includes(edge.id) ? undefined : 0 }}
                  d={path(edge.source, edge.target)}
                />
              </g>
            ))}
          </svg>
          {shown.map((card) => {
            const p = points.get(card.id)!;
            const worker = scene?.workers.find((w) => w.id === card.call_id);
            return (
              <button
                key={card.id}
                data-canvas-card={card.id}
                data-card-kind={card.kind}
                data-round={card.round_id ?? ""}
                className={`cc-card ${card.state}${selected === card.id ? " selected" : ""}${arrivals.includes(card.id) ? " arrived" : ""}`}
                style={
                  {
                    left: p.x,
                    top: p.y,
                    "--role": colors[card.role] ?? colors.expert,
                  } as CSSProperties
                }
                aria-pressed={selected === card.id}
                onClick={(e) => select(card, e.currentTarget)}
              >
                <span className="cc-port" />
                <span className="cc-card-head">
                  <span className="cc-avatar">
                    {card.kind === "artifact"
                      ? "▤"
                      : card.role.slice(0, 1).toUpperCase()}
                  </span>
                  {card.role === "human" ? "研究简报" : label(card.role)}
                  <time>{card.at ? time(card.at) : "时间未记录"}</time>
                </span>
                <h2>{card.title}</h2>
                <p>{card.summary ?? "内容尚未记录"}</p>
                {worker && card.kind === "implementation" && (
                  <Activity worker={worker} />
                )}
                <span className="cc-card-foot">
                  <span>
                    {card.kind === "preparation"
                      ? "准备阶段 · 非正式 Run"
                      : card.attempt_no
                        ? `工作 ${card.attempt_no} · ${label(card.state)}`
                        : label(card.state)}
                  </span>
                  <span>展开 ↗</span>
                </span>
                <span className="cc-port out" />
              </button>
            );
          })}
          {(graph?.rounds ?? []).map((round) => {
            const members = cards.filter((c) => c.round_id === round.id);
            const y = Math.min(...members.map((c) => points.get(c.id)!.y));
            const x = Math.min(...members.map((c) => points.get(c.id)!.x));
            return folded.includes(round.id) ? (
              <button
                key={round.id}
                className="cc-round-summary"
                style={{ left: x, top: y }}
                onClick={() => {
                  inspect();
                  setFolded((old) => old.filter((id) => id !== round.id));
                }}
              >
                <strong>{round.title}</strong>
                <p>
                  {round.attempts.length} 项工作 · {members.length} 项内容
                </p>
                <span>展开</span>
              </button>
            ) : (
              <button
                key={round.id}
                className="cc-round-label"
                style={{ left: x, top: y - 45 }}
                onClick={() => {
                  inspect();
                  setFolded((old) => [...old, round.id]);
                }}
              >
                {round.title} · 折叠
              </button>
            );
          })}
        </div>
        {!cards.length && (
          <div className="cc-empty">
            {scene ? "暂无可确认的内容记录" : "选择任务与准备 / 运行"}
          </div>
        )}
        <div className="cc-toolbar">
          <button aria-label="缩小画布" onClick={() => zoom(1 / 1.2)}>
            −
          </button>
          <button
            onClick={() => {
              inspect();
              const scale = Math.min(
                (size.width - 35) / worldWidth,
                (size.height - 35) / worldHeight,
              );
              setCamera({ x: 18, y: 18, scale: Math.max(0.1, scale) });
            }}
          >
            全图
          </button>
          <button aria-label="放大画布" onClick={() => zoom(1.2)}>
            ＋
          </button>
          <span />
          <button
            aria-pressed={following}
            onClick={() => {
              setFollowing(true);
              onFollow();
              if (latest) {
                if (latest.round_id)
                  setFolded((old) =>
                    old.filter((id) => id !== latest.round_id),
                  );
                focus(latest, size.width < 700 ? 0.87 : 0.82);
              }
            }}
          >
            跟随最新
          </button>
          <button
            aria-pressed={reduced}
            onClick={() => setManualReduced(!manualReduced)}
          >
            {reduced ? "减少动态效果" : "动效"}
          </button>
        </div>
      </div>
      {scene?.kind === "preparation" && (
        <div className="cc-preparation-materials">
          <span>准备阶段 · 此记录不是正式运行</span>
          {scene.preparation_materials?.map((material) => (
            <button
              key={material.id}
              onClick={(e) => {
                inspect();
                onOpen(material, e.currentTarget);
              }}
            >
              {material.name}
            </button>
          ))}
          {scene.result.reason && <span>{scene.result.reason}</span>}
        </div>
      )}
      <section
        className={`cc-timeline${timelineOpen ? " open" : ""}`}
        aria-label="Agent 时间轴"
      >
        <div className="cc-timeline-header">
          <button
            aria-expanded={timelineOpen}
            onClick={() => setTimelineOpen(!timelineOpen)}
          >
            {timelineOpen ? "⌄" : "⌃"} Agent 时间轴
          </button>
          <span>{scene?.workers.length ?? 0} 次调用</span>
        </div>
        {timelineOpen && (
          <div className="cc-tracks">
            <div className="cc-track-list">
              {!!known.length && (
                <div className="cc-ruler">
                  <time>{time(new Date(min).toISOString())}</time>
                  <time>{time(new Date(max).toISOString())}</time>
                </div>
              )}
              <div
                className="cc-track cc-overall-track"
                aria-label="整体泳道：Expert 与 Designer"
                style={{ height: overallHeight }}
              >
                <span title="Expert 与 Designer 的整体协作过程">整体</span>
                <div
                  className="cc-track-line"
                  style={{ height: overallHeight - 4 }}
                >
                  {overallSpans.map(({ worker, lane }) =>
                    timelineSpan(worker, true, lane),
                  )}
                  {!!overallUnknown.length && (
                    <div
                      className="cc-overall-unknown"
                      style={{ top: laneEnds.length * 22 }}
                    >
                      {overallUnknown.map((worker) => timelineSpan(worker))}
                    </div>
                  )}
                  {!overallWorkers.length && (
                    <span className="cc-overall-empty">
                      暂无 Expert 或 Designer 调用
                    </span>
                  )}
                </div>
              </div>
              {scene?.workers.map((worker) => {
                return (
                  <div
                    className="cc-track"
                    key={worker.id}
                    style={
                      {
                        "--role": colors[worker.role] ?? colors.expert,
                      } as CSSProperties
                    }
                  >
                    <span title={label(worker.role)}>
                      {label(worker.role)}
                      {worker.attempt_no ? " · " + worker.attempt_no : ""}
                    </span>
                    <div className="cc-track-line">{timelineSpan(worker)}</div>
                  </div>
                );
              })}
              {!scene?.workers.length && <p>暂无可确认的调用时间</p>}
              <svg
                className="cc-timeline-links"
                aria-hidden="true"
                viewBox={`0 0 1000 ${Math.max(29, timelineWorkers.length * 29)}`}
                preserveAspectRatio="none"
                style={{
                  height: timelineWorkers.length * 29,
                  top: (known.length ? 24 : 0) + overallHeight,
                }}
              >
                {timelineLinks.map(({ edge, a, b, x }) => (
                  <g key={edge.id}>
                    <path d={`M ${x} ${a * 29 + 11} V ${b * 29 + 11}`} />
                    <circle cx={x} cy={b * 29 + 11} r="2" />
                  </g>
                ))}
              </svg>
            </div>
          </div>
        )}
      </section>
      {fact && (
        <aside
          className="cc-fact"
          aria-label="内容详情"
          style={{ bottom: timelineOpen ? 218 : 46 }}
        >
          <button
            className="cc-fact-close"
            aria-label="关闭内容详情"
            onClick={() => {
              setFactId(null);
              factOpener.current?.focus({ preventScroll: true });
            }}
          >
            ×
          </button>
          <span>
            {label(fact.role)} · {label(fact.state)}
          </span>
          <h2 ref={factHeading} tabIndex={-1}>
            {fact.title}
          </h2>
          <p>{fact.summary ?? "内容尚未记录"}</p>
          {fact.kind === "brief" && (
            <p>
              {scene?.run_brief?.version === "matched"
                ? "简报版本已与本次运行合同核对"
                : "简报历史版本无法确认；仅显示本次运行保存的目标"}
            </p>
          )}
          {fact.at && <time>{time(fact.at)}</time>}
          {fact.attempt_no !== null && (
            <button
              onClick={(e) => {
                setFactId(null);
                onWork(fact.attempt_no!, e.currentTarget);
              }}
            >
              查看关联工作
            </button>
          )}
          {fact.call_id && (
            <button
              onClick={(e) => {
                const worker = scene?.workers.find(
                  (w) => w.id === fact.call_id,
                );
                if (worker) {
                  setFactId(null);
                  onWorker(worker, e.currentTarget);
                }
              }}
            >
              查看此次调用
            </button>
          )}
        </aside>
      )}
    </section>
  );
}
