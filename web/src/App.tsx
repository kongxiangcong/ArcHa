import { useCallback, useEffect, useRef, useState } from "react";
import { enc, get, useResource } from "./api";
import { useRunControl } from "./useRunControl";
import { ResearchDesk } from "./ResearchDesk";
import { ResearchCanvas } from "./ResearchCanvas";
import logo from "../../docs/assets/archa-aha-orange.svg";
import { poll } from "./poll";
import { Activity } from "./Activity";
import { Inspection, MaterialReader } from "./Inspection";
import type { Material } from "./types";
import { CurrentProgress } from "./CurrentProgress";
import { Alert, Badge, label, time, preparationLabel } from "./components";
import type {
  Envelope,
  Overview,
  Ref,
  TaskDetail,
  Workbench,
  WorkItem,
  WorkItemsPage,
  WorkerSummary,
} from "./types";

export function useSelection() {
  const [query, setQuery] = useState(
    () => new URLSearchParams(location.search),
  );
  useEffect(() => {
    const pop = () => setQuery(new URLSearchParams(location.search));
    addEventListener("popstate", pop);
    return () => removeEventListener("popstate", pop);
  }, []);
  const change = useCallback(
    (values: Record<string, string | null>, replace = false) => {
      setQuery((old) => {
        const next = new URLSearchParams(old);
        Object.entries(values).forEach(([key, value]) =>
          value ? next.set(key, value) : next.delete(key),
        );
        const url =
          location.pathname + (next.size ? "?" + next.toString() : "");
        if (url !== location.pathname + location.search)
          history[replace ? "replaceState" : "pushState"](null, "", url);
        return next;
      });
    },
    [],
  );
  return [query, change] as const;
}

function useWorkItems(
  run: string,
  scope: string,
  refresh: number,
  target: number | null,
) {
  const [revision, setRevision] = useState(0);
  const pages = useRef({ key: "", count: 1 });
  const [state, setState] = useState<{
    key: string;
    items: WorkItem[];
    total: number;
    more: boolean;
    error?: string;
  }>({ key: "", items: [], total: 0, more: false });
  const key = run + "/" + scope;
  if (pages.current.key !== key) pages.current = { key, count: 1 };
  useEffect(() => {
    if (!run) return;
    let active = true,
      pending = false;
    const controller = new AbortController();
    async function read() {
      if (pending) return;
      pending = true;
      try {
        let cursor: string | null = null,
          total = 0;
        const items: WorkItem[] = [];
        let count = 0;
        do {
          const value: Envelope<WorkItemsPage> = await get(
            `/runs/${enc(run)}/work-items?scope=${scope}&limit=100${cursor ? "&cursor=" + enc(cursor) : ""}`,
            controller.signal,
          );
          items.push(...value.data.items);
          total = value.data.total;
          cursor = value.next_cursor;
          count++;
        } while (
          cursor &&
          (count < pages.current.count ||
            (scope === "all" &&
              target !== null &&
              !items.some((item) => item.attempt_no === target)))
        );
        if (active) {
          pages.current.count = count;
          setState({ key, items, total, more: !!cursor });
        }
      } catch (error) {
        if (active && !controller.signal.aborted)
          setState((old) => ({
            ...(old.key === key
              ? old
              : { key, items: [], total: 0, more: false }),
            error: (error as Error).message,
          }));
      } finally {
        pending = false;
      }
    }
    const stop = poll(read, 1500);
    return () => {
      active = false;
      controller.abort();
      stop();
    };
  }, [run, scope, key, revision, refresh, target]);
  return {
    ...(state.key === key
      ? state
      : { items: [], total: 0, more: false, error: undefined }),
    loadMore: () => {
      pages.current.count++;
      setRevision((n) => n + 1);
    },
  };
}

export default function App() {
  const [query, change] = useSelection();
  const [refresh, setRefresh] = useState(0);
  const [layout, setLayout] = useState(
    () => sessionStorage.getItem("archa-layout") ?? "canvas",
  );
  function chooseLayout(value: string) {
    setLayout(value);
    sessionStorage.setItem("archa-layout", value);
  }

  const topicViews = useRef(
    new Map<
      string,
      {
        task: string;
        run: string;
        attempt: string | null;
        call: string | null;
        detail: boolean;
        scroll: number;
      }
    >(),
  );
  const restoreScroll = useRef<number | null>(null);
  const [navExpanded, setNavExpanded] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("archa-theme") ?? "light",
  );
  const [detail, setDetail] = useState(
    () => !!(query.get("attempt") || query.get("call")),
  );
  const [material, setMaterial] = useState<Material | null>(null);
  const materialOpener = useRef<HTMLElement | null>(null);
  const materialPositions = useRef<
    { element: Element; top: number; left: number }[]
  >([]);
  const closeMaterial = useCallback(() => {
    setMaterial(null);
    requestAnimationFrame(() => {
      for (const { element, top, left } of materialPositions.current) {
        element.scrollTop = top;
        element.scrollLeft = left;
      }
      materialOpener.current?.focus({ preventScroll: true });
    });
  }, []);
  const origin = useRef<HTMLElement | null>(null);
  const detailRef = useRef<HTMLElement>(null);
  const overview = useResource<Overview>("/overview", 5000, refresh);
  const o = overview.value?.data;
  const topic = query.get("topic") ?? o?.tasks[0]?.topic ?? "legacy";
  const topics = [...new Set(o?.tasks.map((item) => item.topic) ?? [])];
  const visibleTasks = o?.tasks.filter((item) => item.topic === topic) ?? [];
  const taskId = query.get("task") ?? visibleTasks[0]?.id ?? "history";
  const runId = query.get("run") ?? "";
  const scope = query.get("filter") === "attention" ? "attention" : "all";
  const task = useResource<TaskDetail>(
    taskId !== "history" ? `/research-tasks/${enc(taskId)}` : null,
    5000,
    refresh,
  );
  const t = task.value?.data;
  const workbench = useResource<Workbench>(
    runId ? `/runs/${enc(runId)}/workbench` : null,
    1500,
    refresh,
  );
  const scene = workbench.value?.data;
  const control = useRunControl(runId, scene?.control_request);
  const stopDialog = useRef<HTMLDialogElement>(null);
  const stopButton = useRef<HTMLButtonElement>(null);
  const cancelStop = useRef<HTMLButtonElement>(null);
  const [stopRun, setStopRun] = useState<string | null>(null);
  useEffect(() => {
    const dialog = stopDialog.current;
    if (!dialog) return;
    if (stopRun && stopRun === runId) {
      if (!dialog.open) dialog.showModal();
      cancelStop.current?.focus();
    } else if (dialog.open) dialog.close();
  }, [stopRun, runId]);
  function closeStop() {
    stopDialog.current?.close();
    setStopRun(null);
    stopButton.current?.focus();
  }
  const stopping = control.busy && control.action === "stop";
  const resuming = control.busy && control.action === "resume";
  const controlAction =
    !resuming &&
    (scene?.execution === "paused" || scene?.execution === "blocked")
      ? "resume"
      : "pause";
  const selectedNo = Number(query.get("attempt")) || null;
  const work = useWorkItems(runId, scope, refresh, selectedNo);
  useEffect(() => {
    if (restoreScroll.current !== null && (work.items.length || !runId)) {
      const element = document.querySelector(".work-scroll");
      if (element) element.scrollTop = restoreScroll.current;
      restoreScroll.current = null;
    }
  }, [topic, work.items.length, runId]);
  const selectedCall = query.get("call");
  const selectedItems = useRef<{ run: string; items: Map<number, WorkItem> }>({
    run: runId,
    items: new Map(),
  });
  if (selectedItems.current.run !== runId)
    selectedItems.current = { run: runId, items: new Map() };
  work.items.forEach((item) =>
    selectedItems.current.items.set(item.attempt_no, item),
  );
  const selected = selectedNo
    ? selectedItems.current.items.get(selectedNo)
    : undefined;
  const worker = scene?.workers.find((w) => w.id === selectedCall);
  const located = useRef<string | null>(null);
  useEffect(() => {
    if (layout !== "list") {
      located.current = null;
      return;
    }
    const key = selectedNo ? runId + "/" + selectedNo : null;
    if (!key) {
      located.current = null;
      return;
    }
    if (located.current === key) return;
    const target = document.querySelector<HTMLElement>(
      `[data-attempt="${selectedNo}"]`,
    );
    if (target) {
      target.scrollIntoView({ block: "nearest" });
      located.current = key;
    }
  }, [runId, selectedNo, work.items, layout]);
  const runs: Ref[] =
    taskId === "history" ? (o?.unlinked_runs ?? []) : (t?.runs ?? []);
  const following = query.get("follow") === "1";
  const activeRuns = runs.filter(
    (item) => item.kind === "execution" && item.recorded_state === "active",
  );
  const followTarget = activeRuns.length === 1 ? activeRuns[0] : null;
  useEffect(() => {
    if (following && followTarget && followTarget.id !== runId) {
      change({ run: followTarget.id, attempt: null, call: null }, true);
      setMaterial(null);
      setDetail(false);
    }
  }, [following, followTarget?.id, runId, change]);
  useEffect(() => {
    if (layout !== "canvas" || runId) return;
    const initial = followTarget ?? (runs.length === 1 ? runs[0] : null);
    if (initial) change({ run: initial.id }, true);
  }, [
    layout,
    runId,
    followTarget?.id,
    runs.map((item) => item.id).join("|"),
    change,
  ]);
  const title =
    t?.task.title ?? (taskId === "history" ? "运行历史" : "工作现场");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("archa-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (detail) detailRef.current?.focus();
  }, [detail]);
  useEffect(() => {
    if (!detail) return;
    const update = () => {
      const bottom = document
        .querySelector(".runbar")
        ?.getBoundingClientRect().bottom;
      if (bottom !== undefined)
        detailRef.current?.style.setProperty(
          "--inspector-top",
          `${Math.ceil(bottom + 8)}px`,
        );
    };
    const observer = new ResizeObserver(update);
    document
      .querySelectorAll(".selectors,.follow-bar,.runbar")
      .forEach((element) => observer.observe(element));
    update();
    return () => observer.disconnect();
  }, [detail, material]);
  const closeDetail = useCallback(() => {
    setDetail(false);
    origin.current?.focus();
  }, []);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (stopDialog.current?.open) return;
      if (event.key === "Escape" && material) {
        event.preventDefault();
        closeMaterial();
        return;
      }
      if (event.key === "Escape" && detail) {
        event.preventDefault();
        closeDetail();
      }
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, [detail, closeDetail, material, closeMaterial]);
  function chooseWork(item: WorkItem, target: HTMLElement) {
    origin.current = target;
    change({
      attempt: String(item.attempt_no),
      call: item.calls.at(-1) ?? null,
    });
    setDetail(true);
    requestAnimationFrame(() => {
      const targetCall = item.calls.at(-1);
      Array.from(document.querySelectorAll<HTMLElement>("[data-call]"))
        .find((element) => element.dataset.call === targetCall)
        ?.scrollIntoView({ block: "nearest" });
    });
  }
  function chooseWorker(item: WorkerSummary, target: HTMLElement) {
    origin.current = target;
    change({
      attempt: item.attempt_no ? String(item.attempt_no) : null,
      call: item.id,
      filter: null,
    });
    setDetail(true);
    requestAnimationFrame(() =>
      document
        .querySelector<HTMLElement>(`[data-attempt="${item.attempt_no}"]`)
        ?.scrollIntoView({ block: "nearest" }),
    );
  }
  function selectTask(value: string) {
    change({ task: value, run: null, attempt: null, call: null, follow: null });
    setDetail(false);
    setMaterial(null);
  }
  return (
    <div className={`app${layout === "canvas" ? " canvas-mode" : ""}`}>
      <dialog
        ref={stopDialog}
        className="stop-dialog"
        aria-labelledby="stop-heading"
        aria-describedby="stop-description"
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const buttons =
            event.currentTarget.querySelectorAll<HTMLButtonElement>("button");
          const first = buttons[0],
            last = buttons[buttons.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        onCancel={(event) => {
          event.preventDefault();
          closeStop();
        }}
      >
        <h2 id="stop-heading">停止当前运行？</h2>
        <p id="stop-description">
          停止会取消当前调用并阻止后续派发。已有工作和结果保留；停止不代表任务完成。
        </p>
        <div className="dialog-actions">
          <button className="btn" ref={cancelStop} onClick={closeStop}>
            取消
          </button>
          <button
            className="btn primary"
            onClick={() => {
              const target = stopRun;
              closeStop();
              if (target === runId && scene?.control.stop.enabled)
                void control.submit("stop");
            }}
          >
            确认停止
          </button>
        </div>
      </dialog>
      <header className="topbar">
        <a className="brand" href="/" aria-label="ArcHa 工作现场">
          <img className="brand-logo" src={logo} alt="ArcHa" />
        </a>
        <span className="breadcrumb">
          {o?.project.display_name ?? "项目"} / 工作现场
        </span>
        <div className="top-right">
          <div className="layout-switch" aria-label="工作台视图">
            <button
              aria-pressed={layout === "canvas"}
              onClick={() => chooseLayout("canvas")}
            >
              画布
            </button>
            <button
              aria-pressed={layout === "list"}
              onClick={() => chooseLayout("list")}
            >
              工作列表
            </button>
          </div>
          {o?.project.source_mode === "demo" && (
            <span className="mode">演示数据 · 只读</span>
          )}
          <button
            className="icon-button"
            aria-label={theme === "light" ? "切换深色主题" : "切换浅色主题"}
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
          >
            {theme === "light" ? "◐" : "◑"}
          </button>
        </div>
      </header>
      <div className={`workspace${navExpanded ? " nav-expanded" : ""}`}>
        <nav className="navrail" aria-label="工作台导航">
          <button
            className="icon-button"
            aria-label={navExpanded ? "收起导航" : "展开导航"}
            aria-expanded={navExpanded}
            onClick={() => setNavExpanded(!navExpanded)}
          >
            ☰<span className="nav-label">收起导航</span>
          </button>
          <button
            className="icon-button current"
            aria-label="工作现场"
            onClick={closeDetail}
          >
            ≡<span className="nav-label">工作现场</span>
          </button>
        </nav>
        <main className="main">
          <div className="selectors">
            <label>
              专题
              <select
                aria-label="选择专题"
                value={topic}
                onChange={(e) => {
                  topicViews.current.set(topic, {
                    task: taskId,
                    run: runId,
                    attempt: query.get("attempt"),
                    call: query.get("call"),
                    detail,
                    scroll:
                      document.querySelector(".work-scroll")?.scrollTop ?? 0,
                  });
                  const saved = topicViews.current.get(e.target.value);
                  restoreScroll.current = saved?.scroll ?? 0;
                  change({
                    topic: e.target.value,
                    task: saved?.task ?? null,
                    run: saved?.run ?? null,
                    attempt: saved?.attempt ?? null,
                    call: saved?.call ?? null,
                    follow: null,
                  });
                  setDetail(saved?.detail ?? false);
                  setMaterial(null);
                }}
              >
                {topics.map((name) => (
                  <option key={name} value={name}>
                    {name === "legacy" ? "原有研究" : name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              任务
              <select
                aria-label="选择任务"
                value={taskId}
                onChange={(e) => selectTask(e.target.value)}
              >
                {visibleTasks.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.title}
                  </option>
                ))}
                <option value="history">未关联运行与准备历史</option>
              </select>
            </label>
            <label>
              运行
              <select
                aria-label="选择运行"
                value={runId}
                onChange={(e) => {
                  change({
                    run: e.target.value,
                    attempt: null,
                    call: null,
                    follow: null,
                  });
                  setMaterial(null);
                  setDetail(false);
                }}
              >
                <option value="">请选择运行</option>
                {runs.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.display_label ?? "运行记录"}
                    {x.recorded_state === "closed" ? " · 已结束" : ""}
                  </option>
                ))}
                {runId && !runs.some((x) => x.id === runId) && (
                  <option value={runId}>
                    显式链接 · {scene?.display_label ?? "读取中"}
                  </option>
                )}
              </select>
            </label>
            <button className="btn" onClick={() => setRefresh((n) => n + 1)}>
              刷新
            </button>
          </div>
          <div
            className="follow-bar"
            hidden={
              layout === "canvas" &&
              activeRuns.length <= 1 &&
              (!followTarget || following || followTarget.id === runId)
            }
          >
            <label>
              <input
                type="checkbox"
                checked={following}
                onChange={(e) =>
                  change({ follow: e.target.checked ? "1" : null })
                }
              />{" "}
              跟随此任务的当前运行
            </label>
            {activeRuns.length > 1 && <span>有多个当前运行，请明确选择</span>}
            {!following && followTarget && followTarget.id !== runId && (
              <button
                className="link-button"
                onClick={() =>
                  change({ run: followTarget.id, attempt: null, call: null })
                }
              >
                有当前运行 · 前往查看
              </button>
            )}
          </div>
          <div className="runbar">
            <div className="run-status" role="status">
              <span className={`status-dot ${scene?.execution ?? ""}`} />
              <strong>
                {scene
                  ? scene.kind === "preparation"
                    ? preparationLabel(scene.execution)
                    : label(scene.execution)
                  : runId
                    ? "读取运行中"
                    : "未选择运行"}
              </strong>
              <span className="run-message">
                {control.sending
                  ? control.action === "resume"
                    ? "正在提交继续请求"
                    : control.action === "stop"
                      ? "正在提交停止请求"
                      : "正在提交暂停请求"
                  : (control.record?.reason ??
                    scene?.control[controlAction].reason ??
                    "选择已有运行查看工作现场")}
              </span>
            </div>
            <div className="run-actions">
              <button
                className="btn primary"
                disabled={
                  stopping ||
                  !scene?.control[controlAction].enabled ||
                  (control.busy && !resuming)
                }
                onClick={() => void control.submit(controlAction)}
              >
                {stopping
                  ? controlAction === "resume"
                    ? "继续"
                    : "暂停"
                  : control.sending
                    ? "提交中"
                    : resuming
                      ? "暂停"
                      : control.busy
                        ? "等待暂停"
                        : controlAction === "resume"
                          ? "继续"
                          : "暂停"}
              </button>
              <button
                className="btn"
                ref={stopButton}
                disabled={!scene?.control.stop.enabled || stopping}
                onClick={() => setStopRun(runId)}
              >
                {stopping ? "等待停止" : "停止"}
              </button>
            </div>
          </div>
          <Alert error={control.error} />
          {control.record?.run.execution_unknown && (
            <div className="notice" role="status">
              仍有执行结果待确认，未将其视为已结束。
            </div>
          )}
          <Alert error={overview.error} stale={!!o} />
          <Alert error={task.error} stale={!!t} />
          <Alert error={workbench.error} stale={!!scene} />
          <Alert error={work.error} stale={!!work.items.length} />
          <div className="heading">
            <h1>{title}</h1>
            <p className="goal">
              {scene?.goal ??
                t?.briefs[0]?.goal ??
                "选择任务与运行，查看已记录的工作进展。"}
            </p>
            {scene?.availability === "partial" && (
              <p className="muted">
                部分历史内容不可用，当前仅展示可确认的记录。
              </p>
            )}
            {scene?.result.reason && (
              <p className="result-message">
                {scene.result.complete === true
                  ? "交付已完成"
                  : scene.result.complete === false
                    ? "交付尚未完成"
                    : "当前结果"}
                ：{scene.result.reason}
              </p>
            )}
            {scene?.result.gaps && (
              <p className="muted">尚待完成：{scene.result.gaps}</p>
            )}
            {scene?.stop_reason && (
              <p className="muted">
                {scene.execution === "paused" ? "暂停说明" : "结束原因"}：
                {scene.stop_reason}
              </p>
            )}
          </div>
          <CurrentProgress key={`progress:${taskId}:${runId}`} scene={scene} />
          {layout === "canvas" ? (
            <ResearchCanvas
              key={runId}
              scope={runId || taskId}
              scene={scene}
              task={t}
              hidden={!!material}
              selectedNo={selectedNo}
              selectedCall={selectedCall}
              onInspect={() => {
                if (following) change({ follow: null });
              }}
              onFollow={() => change({ follow: "1" })}
              onWork={(attempt, opener) => {
                origin.current = opener;
                change({ attempt: String(attempt), call: null });
                setDetail(true);
              }}
              onFactOpen={() => setDetail(false)}
              onWorker={chooseWorker}
              onOpen={(item, opener) => {
                materialPositions.current = [
                  ...document.querySelectorAll(
                    ".main,.inspector-content,.work-scroll,.worker-scroll",
                  ),
                ].map((element) => ({
                  element,
                  top: element.scrollTop,
                  left: element.scrollLeft,
                }));
                materialOpener.current = opener;
                setMaterial(item);
              }}
            />
          ) : (
            <ResearchDesk
              key={runId}
              scene={scene}
              hidden={!!material}
              onOpen={(item, opener) => {
                materialPositions.current = [
                  ...document.querySelectorAll(
                    ".main,.inspector-content,.work-scroll,.worker-scroll",
                  ),
                ].map((element) => ({
                  element,
                  top: element.scrollTop,
                  left: element.scrollLeft,
                }));
                materialOpener.current = opener;
                setMaterial(item);
              }}
              onChoose={(attempt) => {
                change({ attempt: String(attempt), call: null });
                setDetail(true);
              }}
            />
          )}
          <div className="content" hidden={!!material || layout === "canvas"}>
            <section className="work-pane" aria-label="工作进展">
              <div className="panel-heading">
                <h2>
                  工作进展 <span className="count">{work.total}</span>
                </h2>
                <div className="segmented" aria-label="工作筛选">
                  <button
                    aria-pressed={scope === "all"}
                    onClick={() => change({ filter: null })}
                  >
                    全部
                  </button>
                  <button
                    aria-pressed={scope === "attention"}
                    onClick={() => change({ filter: "attention" })}
                  >
                    需关注
                  </button>
                </div>
              </div>
              <div className="work-scroll" tabIndex={0} aria-label="工作时间线">
                {work.items.map((item, i) => (
                  <div className="work-row" key={item.id}>
                    <button
                      className="work-button t-resize"
                      aria-pressed={selectedNo === item.attempt_no}
                      data-attempt={item.attempt_no}
                      onClick={(e) => chooseWork(item, e.currentTarget)}
                    >
                      <span className={`step-icon ${item.stage}`}>
                        {item.stage === "completed"
                          ? "✓"
                          : item.needs_attention
                            ? "!"
                            : String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="work-copy">
                        <span className="work-title-line">
                          <strong className="work-title">{item.title}</strong>
                          <Badge value={item.stage} />
                        </span>
                        <span className="work-description">
                          {item.goal ?? "目标内容未记录"}
                        </span>
                        <span className="work-meta">
                          {item.reason ?? item.summary ?? "查看工作与调用"}
                          {item.calls.length > 0 &&
                            ` · ${item.calls.length} 次调用`}
                        </span>
                      </span>
                    </button>
                    {item.dependencies.length > 0 && (
                      <div className="dependencies">
                        前序工作：
                        {item.dependencies.map((d, index) => (
                          <button
                            key={index}
                            className="link-button"
                            disabled={!d.attempt_no}
                            onClick={(e) => {
                              origin.current = e.currentTarget;
                              change({
                                attempt: d.attempt_no
                                  ? String(d.attempt_no)
                                  : null,
                                filter: null,
                                call: null,
                              });
                              setDetail(true);
                            }}
                          >
                            {d.title ?? "工作记录不可用"}
                            {item.blocked_by.some(
                              (b) =>
                                b === d.work_id ||
                                b.startsWith(d.work_id + ":"),
                            )
                              ? " · 等待"
                              : ""}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {work.more && (
                  <button className="btn" onClick={work.loadMore}>
                    加载更多工作
                  </button>
                )}
                {!work.items.length && (
                  <div className="empty">
                    <h3>
                      {runId
                        ? scope === "attention"
                          ? "暂无需要关注的工作"
                          : "暂无工作记录"
                        : "选择一个运行"}
                    </h3>
                    <p>
                      {runId
                        ? "已有内容将随实际记录更新。"
                        : "运行选择不会启动或修改任务。"}
                    </p>
                  </div>
                )}
              </div>
            </section>
            <section className="workers-pane" aria-label="Worker 活动">
              <div className="panel-heading">
                <h2>
                  Worker 活动{" "}
                  <span className="count">{scene?.workers.length ?? 0}</span>
                </h2>
              </div>
              <div
                className="worker-scroll"
                tabIndex={0}
                aria-label="Worker 列表"
              >
                {scene?.workers
                  .slice()
                  .sort(
                    (a, b) =>
                      Number(b.state === "pending") -
                      Number(a.state === "pending"),
                  )
                  .map((w, index) => (
                    <button
                      className={`worker${w.id === selectedCall || (w.attempt_no === selectedNo && selectedNo !== null) ? " selected" : ""}`}
                      key={w.id}
                      data-call={w.id}
                      onClick={(e) => chooseWorker(w, e.currentTarget)}
                    >
                      <span className="worker-top">
                        <span className="avatar">
                          {w.role[0]?.toUpperCase()}
                        </span>
                        <span>
                          <strong className="worker-name">
                            {label(w.role)}
                          </strong>
                          <span className="worker-purpose">
                            调用 {index + 1}
                          </span>
                        </span>
                        <Badge value={w.state} />
                      </span>
                      <span className="worker-task">
                        {w.attempt_no === null
                          ? "运行级协调"
                          : `工作 ${w.attempt_no}`}
                      </span>
                      {w.error && (
                        <span className="activity-line">{w.error}</span>
                      )}
                      <Activity worker={w} />
                      <span className="activity-time">
                        {time(w.ended_at ?? w.started_at)}
                      </span>
                    </button>
                  ))}
                {!scene?.workers.length && (
                  <p className="empty">暂无调用记录</p>
                )}
                {scene?.workers_truncated && (
                  <p className="muted">仅展示最近 200 次调用。</p>
                )}
              </div>
              <p className="worker-note">
                {scene?.observation_note ?? "选择 Worker 查看相关工作。"}
              </p>
            </section>
          </div>
          {material && (
            <MaterialReader
              key={material.id}
              material={material}
              onClose={closeMaterial}
            />
          )}
          {detail && (
            <aside
              className="inspector t-panel-reveal"
              hidden={!!material}
              aria-label="工作详情"
              tabIndex={-1}
              ref={detailRef}
            >
              <div className="inspector-header">
                <div className="inspector-top">
                  <span className="eyebrow">工作详情</span>
                  <button
                    className="icon-button"
                    aria-label="关闭详情"
                    onClick={closeDetail}
                  >
                    ×
                  </button>
                </div>
                <h2>
                  {selected?.title ??
                    (worker?.attempt_no === null ? "协调当前工作" : "所选工作")}
                </h2>
                {selected && <Badge value={selected.stage} />}
              </div>
              <div className="inspector-content" tabIndex={0}>
                {selected ? (
                  <>
                    <section className="detail-section">
                      <h3>工作目标</h3>
                      <p>{selected.goal ?? "目标内容未记录"}</p>
                    </section>
                    <section className="detail-section">
                      <h3>当前进展</h3>
                      <p>
                        {selected.reason ??
                          selected.summary ??
                          label(selected.stage)}
                      </p>
                    </section>
                  </>
                ) : (
                  <p>选择工作查看进展；运行级调用独立于具体工作。</p>
                )}
                {selectedNo && (
                  <Inspection
                    run={runId}
                    attempt={selectedNo}
                    call={selectedCall}
                    revision={`${refresh}:${
                      scene?.workers
                        .filter((item) => item.attempt_no === selectedNo)
                        .map((item) => `${item.id}:${item.state}`)
                        .join("|") ?? ""
                    }`}
                    onCall={(id) => change({ call: id })}
                    onOpen={(item, opener) => {
                      materialPositions.current = [
                        ...document.querySelectorAll(
                          ".main,.inspector-content,.work-scroll,.worker-scroll",
                        ),
                      ].map((element) => ({
                        element,
                        top: element.scrollTop,
                        left: element.scrollLeft,
                      }));
                      materialOpener.current = opener;
                      setMaterial(item);
                    }}
                  />
                )}
                {worker && (
                  <section className="detail-section">
                    <h3>{label(worker.role)} · 本次调用</h3>
                    <Badge value={worker.state} />
                    {!selectedNo && worker.error && <p>{worker.error}</p>}
                    <Activity worker={worker} expanded />
                  </section>
                )}
              </div>
            </aside>
          )}
          <footer>
            {scene
              ? `最后观察 ${time(workbench.value?.source_observed_at)} · 仅读取已有内容`
              : "未选择准备或运行"}
          </footer>
        </main>
      </div>
    </div>
  );
}
