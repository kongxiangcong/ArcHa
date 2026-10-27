import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, base, enc, get, useResource } from "./api";
import type {
  Artifact,
  Attempt,
  Brief,
  Call,
  Content,
  Envelope,
  MessageItem,
  MessagePage,
  Overview,
  Ref,
  RevisionDetail,
  Run,
  TaskDetail,
  Task,
  Usage,
} from "./types";
import {
  Badge,
  FactView,
  Metrics,
  Problems,
  ReadonlyMessages,
  Requirements,
  SafeMarkdown,
  Sources,
  StateView,
  TaskGraph,
  label,
  time,
} from "./components";
const phases = [
  ["map", "方向地图"],
  ["task", "任务目标"],
  ["onboard", "执行接入"],
  ["loop", "迭代执行"],
  ["acceptance", "交付验收"],
] as const;
function useSelection() {
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
        Object.entries(values).forEach(([k, v]) =>
          v ? next.set(k, v) : next.delete(k),
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
function Alert({ error, stale = false }: { error?: string; stale?: boolean }) {
  return error ? (
    <div className="alert" role="status">
      <strong>
        {stale ? "更新失败，保留上次成功内容；数据可能滞后" : "无法读取"}
      </strong>
      <p>{error}</p>
    </div>
  ) : null;
}
function EnvelopeNotice({ value }: { value?: Envelope<unknown> | null }) {
  const stale = value?.issues.filter((i) =>
    /unreadable|stale|changed|mismatch/.test(i.code),
  );
  return (
    <>
      {stale?.length ? (
        <Alert error={stale.map((i) => i.message).join("；")} stale />
      ) : null}
      <Problems issues={value?.issues} />
    </>
  );
}
function UsageView({ usage }: { usage?: Usage | null }) {
  return (
    <div className="usage">
      <strong>已记录用量</strong>
      {usage ? (
        <>
          <span>
            {usage.scope === "call"
              ? "本次调用"
              : usage.scope === "task"
                ? "整个任务"
                : "所选运行"}{" "}
            · {label(usage.completeness)}
          </span>
          <span>
            tokens{" "}
            {usage.recorded_tokens == null
              ? "未知"
              : usage.recorded_tokens.toLocaleString()}{" "}
            · USD{" "}
            {usage.recorded_usd == null
              ? "未知"
              : usage.recorded_usd.toFixed(4)}{" "}
            · 耗时{" "}
            {usage.recorded_wall_seconds == null
              ? "未知"
              : `${usage.recorded_wall_seconds} s`}
          </span>
          <small>
            准备阶段：
            {usage.includes_preparation == null
              ? "是否包含未确认"
              : usage.includes_preparation
                ? "已包含"
                : "未包含"}
            {usage.note ? ` · ${usage.note}` : ""}
          </small>
        </>
      ) : (
        <span>尚无可确认的账单，tokens / USD 未知</span>
      )}
    </div>
  );
}
function FileList({
  refs,
  selected,
  onSelect,
}: {
  refs: Ref[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="file-list">
      {refs.length ? (
        refs.map((f) => (
          <button
            key={f.id}
            className="file"
            aria-pressed={selected === f.id}
            onClick={() => onSelect(f.id)}
          >
            <span>{f.label}</span>
            <span className="muted">查看 →</span>
          </button>
        ))
      ) : (
        <p className="empty">未发现本阶段产物记录</p>
      )}
    </div>
  );
}
function Briefs({
  briefs,
  onArtifact,
}: {
  briefs: Brief[];
  onArtifact: (id: string) => void;
}) {
  return (
    <>
      {briefs.map((b) => (
        <section className="brief" key={b.id}>
          <h3>{b.path}</h3>
          <Badge value={b.link_state} />
          <p>{b.goal ?? "目标未记录"}</p>
          <p>完成定义：{b.done_when ?? "未记录"}</p>
          <p>范围：{b.scope ?? "未记录"}</p>
          {b.body_artifact_id && (
            <button
              className="link"
              onClick={() => onArtifact(b.body_artifact_id!)}
            >
              阅读 brief 原文
            </button>
          )}
          <Sources meta={b.meta} onArtifact={onArtifact} />
        </section>
      ))}
    </>
  );
}
function MapBody({
  id,
  onArtifact,
  onTask,
  tasks,
}: {
  id: string;
  onArtifact: (id: string) => void;
  onTask: (id: string) => void;
  tasks: Task[];
}) {
  const mapMeta = useResource<Artifact>(`/artifacts/${enc(id)}`, 30000);
  const body = useResource<Content>(`/artifacts/${enc(id)}/content`, 30000);
  const links: Record<string, string> = {};
  tasks.forEach((t) =>
    t.meta.source_refs.forEach((ref) => {
      links[ref.display_path] = t.id;
      const tail = ref.display_path.split("/research/")[1];
      if (tail) links[tail] = t.id;
    }),
  );
  return (
    <section className="map-body">
      <Alert error={body.error} stale={!!body.value} />
      {body.value && (
        <SafeMarkdown
          targets={mapMeta.value?.data.link_targets}
          links={links}
          onArtifact={onArtifact}
          onTask={onTask}
        >
          {body.value.data.content}
        </SafeMarkdown>
      )}
    </section>
  );
}
function ArtifactInspector({
  id,
  onArtifact,
  onTask,
}: {
  id: string;
  onArtifact: (id: string) => void;
  onTask: (id: string) => void;
}) {
  const resource = useResource<Artifact>(`/artifacts/${enc(id)}`, 2000);
  const a = resource.value?.data;
  const [raw, setRaw] = useState(false);
  const [page, setPage] = useState<Envelope<Content> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const chunks = useRef(new Map<number, string>());
  const version = useRef<string | null>(null);
  const preview =
    a?.can_preview &&
    (raw || a.mime?.includes("markdown") || a.display_path.endsWith(".md"));
  useEffect(() => {
    if (!preview) return;
    const ctrl = new AbortController();
    let pending = false;
    const read = async () => {
      if (pending) return;
      pending = true;
      setLoading(true);
      try {
        const value = await get<Content>(
          `/artifacts/${enc(id)}/content?offset=${offset}`,
          ctrl.signal,
        );
        if (ctrl.signal.aborted) return;
        if (version.current !== value.data.content_version) {
          chunks.current.clear();
          version.current = value.data.content_version;
          if (offset) {
            setOffset(0);
            setPage(null);
            return;
          }
        }
        chunks.current.set(value.data.byte_offset, value.data.content);
        const content = [...chunks.current.entries()]
          .sort(([a], [b]) => a - b)
          .map(([, text]) => text)
          .join("");
        setPage({ ...value, data: { ...value.data, content } });
        setError("");
      } catch (e) {
        if (!ctrl.signal.aborted) {
          if (
            offset &&
            e instanceof ApiError &&
            (e.code === "invalid_offset" || e.status === 409)
          ) {
            chunks.current.clear();
            version.current = null;
            setPage(null);
            setOffset(0);
            setError("来源已截断或替换，正在从头重新读取");
          } else setError((e as Error).message);
        }
      } finally {
        pending = false;
        if (!ctrl.signal.aborted) setLoading(false);
      }
    };
    void read();
    const timer = setInterval(() => void read(), 2000);
    return () => {
      ctrl.abort();
      clearInterval(timer);
    };
  }, [id, preview, offset]);
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">产物详情</span>
          <h2>{a?.title ?? "读取产物"}</h2>
        </div>
        <Badge value={a?.availability} />
      </div>
      <div className="panel-body">
        <Alert error={resource.error} stale={!!a} />
        <EnvelopeNotice value={resource.value} />
        {a && (
          <>
            <p className="path">{a.display_path}</p>
            {a.content_is_projection && (
              <p className="notice">
                配置内容仅展示观察所需字段的投影，已省略 workers
                等配置；这不是完整原件，不提供原件下载。下方摘要定位原始来源。
              </p>
            )}
            <dl className="metadata">
              <dt>类型 / 来源</dt>
              <dd>
                {a.kind} · {a.content_origin === "ledger" ? "账本记录" : "文件"}
              </dd>
              <dt>归属</dt>
              <dd>
                {a.owner_refs.map((r) => r.label).join(" / ") || "未记录"}
              </dd>
              <dt>大小 / 摘要</dt>
              <dd>
                {a.size_bytes == null ? "未记录" : `${a.size_bytes} bytes`}
                <code>{a.digest ?? "摘要未记录"}</code>
              </dd>
            </dl>
            <div className="facts">
              {a.key_facts.length ? (
                a.key_facts.map((f, n) => (
                  <FactView
                    key={n}
                    title={`要点 ${n + 1}`}
                    fact={
                      typeof f === "string" ? { text: f, source_refs: [] } : f
                    }
                    onArtifact={onArtifact}
                  />
                ))
              ) : (
                <p className="empty">未记录现有要点，可查看原文</p>
              )}
            </div>
            <div className="toolbar">
              {a.can_preview && (
                <button
                  className="secondary"
                  aria-pressed={raw}
                  onClick={() => setRaw((v) => !v)}
                >
                  {raw
                    ? "返回要点"
                    : a.content_is_projection
                      ? "查看投影内容"
                      : "查看原文"}
                </button>
              )}
              {a.can_download && (
                <a
                  className="secondary"
                  href={`${base}/artifacts/${enc(id)}/content?download=1`}
                >
                  下载原件
                </a>
              )}
            </div>
            <Alert error={error} stale={!!page} />
            <EnvelopeNotice value={page} />
            {loading && <p role="status">读取原文中…</p>}
            {page && preview && (
              <div className="source-content">
                {raw ? (
                  <pre tabIndex={0} aria-label="产物原文">
                    {page.data.content}
                  </pre>
                ) : (
                  <SafeMarkdown
                    targets={a.link_targets}
                    onArtifact={onArtifact}
                    onTask={onTask}
                  >
                    {page.data.content}
                  </SafeMarkdown>
                )}
                {page.data.truncated && (
                  <p className="notice">原文已分页，本段不是完整原件</p>
                )}
                {!page.data.eof && page.data.next_offset != null && (
                  <button
                    className="secondary"
                    disabled={loading}
                    onClick={() => setOffset(page.data.next_offset!)}
                  >
                    继续读取原文
                  </button>
                )}
              </div>
            )}
            <Sources meta={a.meta} onArtifact={onArtifact} />
          </>
        )}
      </div>
    </>
  );
}
function CallInspector({
  id,
  onArtifact,
}: {
  id: string;
  onArtifact: (id: string) => void;
}) {
  const resource = useResource<Call>(`/calls/${enc(id)}`, 2000);
  const c = resource.value?.data;
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [error, setError] = useState("");
  const [reset, setReset] = useState("");
  const [busy, setBusy] = useState(false);
  const cursor = useRef<string | null>(null);
  const [page, setPage] = useState(0);
  useEffect(() => {
    let alive = true,
      pending = false;
    const ctrl = new AbortController();
    const read = async () => {
      if (pending) return;
      pending = true;
      setBusy(true);
      try {
        const result = await get<MessagePage>(
          `/calls/${enc(id)}/messages?limit=100${cursor.current ? "&cursor=" + enc(cursor.current) : ""}`,
          ctrl.signal,
        );
        if (alive) {
          setMessages((old) => {
            const map = new Map(
              (result.data.reset ? [] : old).map((m) => [m.id, m]),
            );
            result.data.items.forEach((m) => map.set(m.id, m));
            return [...map.values()];
          });
          cursor.current = result.next_cursor;
          setReset(result.data.reset_reason ?? "");
          setError("");
        }
      } catch (e) {
        if (alive && !ctrl.signal.aborted) setError((e as Error).message);
      } finally {
        pending = false;
        if (alive) setBusy(false);
      }
    };
    void read();
    const timer = setInterval(() => void read(), 2000);
    return () => {
      alive = false;
      ctrl.abort();
      clearInterval(timer);
    };
  }, [id, page]);
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">调用详情 · 只读</span>
          <h2>{c?.role ?? "读取调用"}</h2>
        </div>
        <Badge value={c?.state.value} />
      </div>
      <div className="panel-body">
        <Alert error={resource.error} stale={!!c} />
        <EnvelopeNotice value={resource.value} />
        {c && (
          <>
            <dl className="metadata">
              <dt>Provider</dt>
              <dd>{c.provider ?? "未记录"}</dd>
              <dt>原始调用 ID</dt>
              <dd>{c.provider_call_id ?? "未记录"}</dd>
              <dt>开始 / 结束</dt>
              <dd>
                {time(c.started_at)} / {time(c.ended_at)}
              </dd>
              <dt>最后活动</dt>
              <dd>{time(c.last_activity_at)}</dd>
              <dt>父调用</dt>
              <dd>{c.parent_call_id ?? "未确认"}</dd>
              <dt>内容可用性</dt>
              <dd>{label(c.transcript_availability)}</dd>
            </dl>
            <UsageView usage={c.usage} />
            <Sources meta={c.meta} onArtifact={onArtifact} />
            <Alert error={error} stale={messages.length > 0} />
            {reset && <p className="notice">内容重置：{reset}</p>}
            <ReadonlyMessages items={messages} />
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setPage((v) => v + 1)}
            >
              {busy ? "读取中…" : "读取后续内容"}
            </button>
            <FileList refs={c.artifacts} selected="" onSelect={onArtifact} />
          </>
        )}
      </div>
    </>
  );
}
export default function App() {
  const [query, change] = useSelection();
  const [refresh, setRefresh] = useState(0);
  const overview = useResource<Overview>("/overview", 30000, refresh);
  const o = overview.value?.data;
  const tasks = o?.tasks ?? [];
  const taskId = query.get("task") ?? tasks[0]?.id ?? "";
  const task = useResource<TaskDetail>(
    taskId ? `/research-tasks/${enc(taskId)}` : null,
    30000,
    refresh,
  );
  const t = task.value?.data;
  const revId =
    query.get("revision") === "all"
      ? ""
      : (query.get("revision") ?? t?.revisions[0]?.id ?? "");
  const revision = useResource<RevisionDetail>(
    revId ? `/task-revisions/${enc(revId)}` : null,
    30000,
    refresh,
  );
  const rd = revision.value?.data;
  const rev = rd?.revision;
  const runs = revId ? (rd?.runs ?? []) : (t?.runs ?? []);
  const runId = query.get("run") ?? runs[0]?.id ?? "";
  const run = useResource<Run>(
    runId ? `/runs/${enc(runId)}` : null,
    2000,
    refresh,
  );
  const r = run.value?.data;
  const runRevision = useResource<RevisionDetail>(
    r?.task_revision_id ? `/task-revisions/${enc(r.task_revision_id)}` : null,
    30000,
    refresh,
  );
  const actualRev = runRevision.value?.data.revision;
  const phase = phases.some(([p]) => p === query.get("phase"))
    ? query.get("phase")!
    : "map";
  const attemptNo =
    query.get("attempt") ??
    String((r?.attempts[0] as Ref & { attempt_no?: number })?.attempt_no ?? 1);
  const attempt = useResource<Attempt>(
    runId && r?.attempts.length
      ? `/runs/${enc(runId)}/attempts/${attemptNo}`
      : null,
    2000,
    refresh,
  );
  const at = attempt.value?.data;
  const artifactId = query.get("artifact") ?? "";
  const callId = query.get("call") ?? "";
  useEffect(() => {
    const defaults: Record<string, string> = {};
    if (t && !query.has("revision") && !query.has("run") && revId)
      defaults.revision = revId;
    if (r && !query.has("run")) defaults.run = r.id;
    if (at && !query.has("attempt")) defaults.attempt = String(at.attempt_no);
    if (Object.keys(defaults).length) change(defaults, true);
  }, [t, r, at, revId, query, change]);
  const onArtifact = useCallback(
    (id: string) => change({ artifact: id, call: null }),
    [change],
  );
  const onTask = useCallback(
    (id: string) =>
      change({
        task: id,
        revision: null,
        run: null,
        attempt: null,
        artifact: null,
        call: null,
      }),
    [change],
  );
  useEffect(() => {
    if (
      o &&
      !query.get("task") &&
      tasks[0] &&
      !query.get("revision") &&
      !query.get("run")
    )
      change({ task: tasks[0].id }, true);
  }, [o, query, tasks, change]);
  const selectedFiles =
    phase === "loop"
      ? (at?.artifacts ?? [])
      : phase === "acceptance"
        ? (r?.report_refs ?? [])
        : phase === "map"
          ? (o?.maps ?? []).map((m) => ({
              id: m.artifact_id ?? m.id,
              label: m.label,
            }))
          : phase === "task"
            ? (t?.artifacts ?? []).concat(rd?.artifacts ?? [])
            : (r?.artifacts ?? []);
  const files = [...new Map(selectedFiles.map((f) => [f.id, f])).values()];
  const calls = phase === "loop" ? (at?.calls ?? []) : (r?.calls ?? []);
  const snap = run.value ?? task.value ?? overview.value;
  return (
    <div className="app">
      <a className="skip" href="#workbench">
        跳到任务白板
      </a>
      <header className="top">
        <a className="brand" href="/">
          <span className="logo">A</span>
          <span>
            ArcHa <span className="brand-sub">/ 观察工作台</span>
          </span>
        </a>
        <span className="mode">
          ● 只读观察 · {label(o?.project.source_mode)}
        </span>
      </header>
      <main id="workbench">
        <div className="navigation">
          <label>
            任务
            <select
              aria-label="选择任务"
              value={taskId}
              onChange={(e) => onTask(e.target.value)}
            >
              <option value="">选择任务</option>
              {tasks.map((x) => (
                <option value={x.id} key={x.id}>
                  {x.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            合同版本
            <select
              aria-label="选择合同版本"
              value={revId || "all"}
              onChange={(e) =>
                change({
                  revision: e.target.value,
                  run: null,
                  attempt: null,
                  artifact: null,
                  call: null,
                })
              }
            >
              <option value="all">全部运行 / 无合同</option>
              {(t?.revisions ?? []).map((x) => (
                <option value={x.id} key={x.id}>
                  {x.execution_task_id} · {x.revision}
                </option>
              ))}
              {o?.unlinked_revisions
                .filter((x) => !t?.revisions.some((y) => y.id === x.id))
                .map((x) => (
                  <option value={x.id} key={x.id}>
                    未关联 · {x.label}
                  </option>
                ))}
            </select>
          </label>
          <label>
            运行
            <select
              aria-label="选择运行"
              value={runId}
              onChange={(e) =>
                change({
                  run: e.target.value,
                  attempt: null,
                  artifact: null,
                  call: null,
                })
              }
            >
              <option value="">未选择运行</option>
              {[
                ...new Map(
                  [
                    ...runs,
                    ...(r ? [{ id: r.id, label: r.source_run_id }] : []),
                    ...(o?.unlinked_runs ?? []),
                  ].map((x) => [x.id, x]),
                ).values(),
              ].map((x) => (
                <option value={x.id} key={x.id}>
                  {x.label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="secondary"
            onClick={() => setRefresh((v) => v + 1)}
          >
            刷新来源
          </button>
        </div>
        <Alert error={overview.error} stale={!!o} />
        <Alert error={task.error} stale={!!t} />
        <Alert error={revision.error} stale={!!rev} />
        <Alert error={run.error} stale={!!r} />
        <EnvelopeNotice value={run.value} />
        <EnvelopeNotice value={revision.value} />
        <EnvelopeNotice value={runRevision.value} />
        <EnvelopeNotice value={task.value} />
        {!o && !overview.error && <p role="status">读取项目材料中…</p>}
        {o && (
          <>
            <section className="heading">
              <div>
                <p className="eyebrow">
                  {o.project.display_name} /{" "}
                  {rev?.execution_task_id ??
                    t?.task.research_task_id ??
                    "研究任务"}
                </p>
                <h1>{t?.task.title ?? rev?.goal ?? "项目观察"}</h1>
                <p className="goal">
                  {(r ? actualRev?.goal : rev?.goal) ??
                    (!r ? t?.briefs[0]?.goal : null) ??
                    "尚未发现可确认归属的任务目标。请选择已有材料。"}
                </p>
              </div>
              <div className="read-time">
                <span>所选运行 {r?.source_run_id ?? "未选择"}</span>
                <span title={snap?.snapshot_at}>
                  读取时间 {time(snap?.snapshot_at)}
                </span>
                <span>最后源记录 {time(snap?.source_observed_at)}</span>
              </div>
            </section>
            <div className="states">
              <StateView title="准备" state={r?.preparation} />
              <StateView title="执行" state={r?.execution} />
              <StateView title="验收" state={r?.acceptance} />
              <UsageView usage={r?.usage} />
            </div>
            <nav className="phases" aria-label="任务阶段">
              {phases.map(([key, name], i) => (
                <button
                  key={key}
                  aria-pressed={phase === key}
                  onClick={() =>
                    change({ phase: key, artifact: null, call: null })
                  }
                >
                  <span className="stage-index">{i + 1}</span>
                  <span>
                    <strong>{name}</strong>
                    <small>
                      {key === "map"
                        ? o.maps.length
                          ? "已有地图"
                          : "未发现地图"
                        : key === "task"
                          ? t || rev
                            ? "已有材料"
                            : "未发现记录"
                          : key === "onboard"
                            ? label(r?.preparation.value)
                            : key === "loop"
                              ? `${r?.attempts.length ?? 0} 轮记录`
                              : label(r?.acceptance.value)}
                    </small>
                  </span>
                </button>
              ))}
            </nav>
            <section className="requirements-strip" aria-label="常驻完成条件">
              <strong>完成条件</strong>
              {(r?.requirements ?? rev?.requirements ?? []).map((req) => (
                <span key={req.id}>
                  {req.id} <Badge value={req.result} />
                </span>
              ))}
              {!(r?.requirements ?? rev?.requirements ?? []).length && (
                <span className="muted">未记录要求，不能推断任务完成</span>
              )}
            </section>
            <div className="columns">
              <section className="work panel">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">
                      {phase === "loop" ? "按轮次回看" : "已有材料"}
                    </span>
                    <h2>{phases.find(([p]) => p === phase)?.[1]}</h2>
                  </div>
                  {phase === "loop" && (
                    <div className="rounds" aria-label="选择轮次">
                      {r?.attempts.map((a, i) => {
                        const n =
                          (a as Ref & { attempt_no?: number }).attempt_no ??
                          i + 1;
                        return (
                          <button
                            key={a.id}
                            aria-pressed={Number(attemptNo) === n}
                            onClick={() =>
                              change({
                                attempt: String(n),
                                artifact: null,
                                call: null,
                              })
                            }
                          >
                            第 {n} 轮
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
                <div className="panel-body">
                  {phase === "map" && (
                    <>
                      <p className="section-intro">
                        任务关系与研究背景。图与下方列表均可进入任务。
                      </p>
                      {tasks.length ? (
                        <>
                          <TaskGraph
                            tasks={tasks}
                            selected={taskId}
                            onTask={onTask}
                          />
                          <div className="task-list">
                            {tasks.map((x) => (
                              <button
                                key={x.id}
                                aria-pressed={x.id === taskId}
                                onClick={() => onTask(x.id)}
                              >
                                {x.title}
                                <small>
                                  {label(x.link_state)} ·{" "}
                                  {x.depends_on.length
                                    ? "依赖 " +
                                      x.depends_on
                                        .map((d) =>
                                          typeof d === "string" ? d : d.label,
                                        )
                                        .join("、")
                                    : "无明确依赖"}
                                </small>
                              </button>
                            ))}
                          </div>
                        </>
                      ) : (
                        <p className="empty">
                          未发现任务清单；直接合同和未关联运行仍可从顶部进入。
                        </p>
                      )}
                      {o.maps.map((m) => (
                        <MapBody
                          tasks={tasks}
                          id={m.artifact_id ?? m.id}
                          key={m.id}
                          onArtifact={onArtifact}
                          onTask={onTask}
                        />
                      ))}
                    </>
                  )}
                  {phase === "task" && (
                    <>
                      <FactView
                        title="所选运行目标"
                        fact={
                          actualRev?.goal
                            ? {
                                text: actualRev.goal,
                                source_refs: actualRev.meta.source_refs,
                              }
                            : !r && rev?.goal
                              ? {
                                  text: rev.goal,
                                  source_refs: rev.meta.source_refs,
                                }
                              : null
                        }
                        onArtifact={onArtifact}
                      />
                      <p className="notice">
                        历史运行按自身冻结合同解释，所选合同不覆盖运行目标。
                      </p>
                      {rev && (
                        <>
                          <p>
                            合同版本：<code>{rev.revision}</code>{" "}
                            <Badge value={rev.link_state} />
                          </p>
                          <Sources meta={rev.meta} onArtifact={onArtifact} />
                        </>
                      )}
                      <Briefs
                        briefs={t?.briefs ?? []}
                        onArtifact={onArtifact}
                      />
                      <Requirements
                        items={r?.requirements ?? rev?.requirements ?? []}
                        onArtifact={onArtifact}
                      />
                    </>
                  )}
                  {phase === "onboard" && (
                    <>
                      <StateView
                        title="明确记录的准备状态"
                        state={r?.preparation}
                      />
                      <p className="notice">
                        准备记录不自动绑定最新合同；只有明确关系会显示为已关联。
                      </p>
                      {r && <Sources meta={r.meta} onArtifact={onArtifact} />}
                      <Briefs
                        briefs={t?.briefs ?? []}
                        onArtifact={onArtifact}
                      />
                    </>
                  )}
                  {phase === "loop" && (
                    <>
                      <Alert error={attempt.error} stale={!!at} />
                      <EnvelopeNotice value={attempt.value} />
                      {at ? (
                        <>
                          <div className="attempt-state">
                            <Badge value={at.execution_state.value} />
                            <span>
                              候选：
                              <code>{at.candidate_commit ?? "未记录"}</code>
                            </span>
                          </div>
                          <div className="facts">
                            {(
                              [
                                ["专家意图", at.intent],
                                ["提出理由", at.rationale],
                                ["开发实际成果", at.execution_summary],
                                ["实验与验证", at.experiment_summary],
                                ["当前结论", at.conclusion],
                                ["剩余缺口", at.gaps],
                                ["已有下一步建议", at.next_step],
                              ] as const
                            ).map(([title, fact]) => (
                              <FactView
                                key={title}
                                title={title}
                                fact={fact}
                                onArtifact={onArtifact}
                              />
                            ))}
                          </div>
                          <Sources meta={at.meta} onArtifact={onArtifact} />
                        </>
                      ) : (
                        <p className="empty">未发现轮次记录</p>
                      )}
                    </>
                  )}
                  {phase === "acceptance" && (
                    <>
                      <StateView title="所选运行验收" state={r?.acceptance} />
                      <p>
                        结束原因：{r?.stop_reason ?? "未记录"}
                        。运行结束与需求通过分别展示。
                      </p>
                      <Requirements
                        items={r?.requirements ?? []}
                        onArtifact={onArtifact}
                      />
                      <Metrics
                        items={r?.metrics ?? []}
                        onArtifact={onArtifact}
                      />
                      <dl className="metadata">
                        {Object.entries(r?.versions ?? {}).map(([k, v]) => (
                          <div className="version" key={k}>
                            <dt>{k}</dt>
                            <dd>
                              <code>{v ?? "未记录"}</code>
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </>
                  )}
                  {phase !== "map" && calls.length > 0 && (
                    <section className="calls">
                      <h3>agent 调用</h3>
                      <div className="call-list">
                        {calls.map((c) => (
                          <button
                            key={c.id}
                            aria-pressed={callId === c.id}
                            onClick={() =>
                              change({ call: c.id, artifact: null })
                            }
                          >
                            {c.label}
                            <small>查看调用记录 →</small>
                          </button>
                        ))}
                      </div>
                    </section>
                  )}
                  <div className="files-heading">
                    <h3>产物与来源</h3>
                    <span>{files.length} 条记录</span>
                  </div>
                  <FileList
                    refs={files}
                    selected={artifactId}
                    onSelect={onArtifact}
                  />
                </div>
              </section>
              <aside
                className="inspector panel"
                aria-label="所选产物或调用详情"
              >
                {callId ? (
                  <CallInspector
                    key={callId}
                    id={callId}
                    onArtifact={onArtifact}
                  />
                ) : artifactId ? (
                  <ArtifactInspector
                    key={artifactId}
                    id={artifactId}
                    onArtifact={onArtifact}
                    onTask={onTask}
                  />
                ) : (
                  <>
                    <div className="section-heading">
                      <div>
                        <span className="eyebrow">证据阅读</span>
                        <h2>产物详情</h2>
                      </div>
                      <span className="muted">尚未选择</span>
                    </div>
                    <div className="panel-body empty-inspector">
                      <span className="document-mark" aria-hidden="true">
                        ≡
                      </span>
                      <h3>从一条记录开始</h3>
                      <p>
                        点击左侧产物查看已有要点与原文；点击 agent
                        调用展开消息、工具结果和来源。
                      </p>
                      <p className="muted">
                        只读观察不会执行工具，也不会推进任务。
                      </p>
                    </div>
                  </>
                )}
              </aside>
            </div>
            <footer>
              <span>
                {o.project.adapter_id} · {o.project.adapter_version} / 来源格式{" "}
                {o.project.source_format ?? "未知"}
              </span>
              <span>
                观察快照不代表执行心跳 ·{" "}
                {o.project.source_mode === "demo"
                  ? "全部为合成演示材料"
                  : "仅显示已有来源"}
              </span>
            </footer>
            <Problems issues={overview.value?.issues} />
            <Sources meta={o.project.meta} onArtifact={onArtifact} />
            <details className="sources">
              <summary>当前来源能力</summary>
              {Object.entries(o.capabilities).map(([k, v]) => (
                <p key={k}>
                  {k} · {label(v)}
                </p>
              ))}
            </details>
          </>
        )}
      </main>
    </div>
  );
}
