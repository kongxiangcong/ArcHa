import { useCallback, useEffect, useRef, useState } from "react";
import { enc, get, useResource } from "./api";
import { useRunControl } from "./useRunControl";
import { Activity } from "./Activity";
import { Inspection, MaterialReader } from "./Inspection";
import type { Material } from "./types";
import { Alert, Badge, label, time } from "./components";
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
    void read();
    const timer = setInterval(() => void read(), 1500);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
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
  const [navExpanded, setNavExpanded] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("archa-theme") ?? "light",
  );
  const [detail, setDetail] = useState(
    () => !!(query.get("attempt") || query.get("call")),
  );
  const [material, setMaterial] = useState<Material | null>(null);
  const materialOpener = useRef<HTMLElement | null>(null);
  const closeMaterial = useCallback(() => {
    setMaterial(null);
    requestAnimationFrame(() => materialOpener.current?.focus());
  }, []);
  const origin = useRef<HTMLElement | null>(null);
  const detailRef = useRef<HTMLElement>(null);
  const overview = useResource<Overview>("/overview", 5000, refresh);
  const o = overview.value?.data;
  const taskId = query.get("task") ?? o?.tasks[0]?.id ?? "history";
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
  }, [runId, selectedNo, work.items]);
  const runs: Ref[] =
    taskId === "history" ? (o?.unlinked_runs ?? []) : (t?.runs ?? []);
  const title =
    t?.task.title ?? (taskId === "history" ? "运行历史" : "工作现场");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("archa-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (detail) detailRef.current?.focus();
  }, [detail]);
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
    change({ task: value, run: null, attempt: null, call: null });
    setDetail(false);
    setMaterial(null);
  }
  return (
    <div className="app">
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
          <span className="brand-mark" aria-hidden="true">
            A
          </span>
          ArcHa
        </a>
        <span className="breadcrumb">
          {o?.project.display_name ?? "项目"} / 工作现场
        </span>
        <div className="top-right">
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
              任务
              <select
                aria-label="选择任务"
                value={taskId}
                onChange={(e) => selectTask(e.target.value)}
              >
                {o?.tasks.map((x) => (
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
                  change({ run: e.target.value, attempt: null, call: null });
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
          <div className="runbar">
            <div className="run-status" role="status">
              <span className={`status-dot ${scene?.execution ?? ""}`} />
              <strong>
                {scene
                  ? label(scene.execution)
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
            <p className="eyebrow">WORKSPACE / 当前任务</p>
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
          <div className="content" hidden={!!material}>
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
                      className="work-button"
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
                {scene?.workers.map((w, index) => (
                  <button
                    className={`worker${w.id === selectedCall || (w.attempt_no === selectedNo && selectedNo !== null) ? " selected" : ""}`}
                    key={w.id}
                    data-call={w.id}
                    onClick={(e) => chooseWorker(w, e.currentTarget)}
                  >
                    <span className="worker-top">
                      <span className="avatar">{w.role[0]?.toUpperCase()}</span>
                      <span>
                        <strong className="worker-name">{label(w.role)}</strong>
                        <span className="worker-purpose">调用 {index + 1}</span>
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
              className="inspector"
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
              : "ArcHa · 工作现场"}
          </footer>
        </main>
      </div>
    </div>
  );
}
