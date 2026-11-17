import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "./api";
import { poll } from "./poll";
import type {
  Content,
  Overview,
  TopicDetail,
  Role,
  Material,
  Excerpt,
  AgentEvent,
} from "./types";

const roles: Record<Role, string> = {
  expert: "Expert",
  executor: "Executor",
  expert_finalize: "Expert · 收尾消化",
  expert_revise: "Expert · 调整探针",
};
const activities = {
  idle: "空闲",
  running: "运行中",
  stopping: "停止中",
  unknown: "未知执行",
};
function Reader({
  path,
  onOpen,
  live = false,
}: {
  path: string;
  onOpen: (path: string) => void;
  live?: boolean;
}) {
  const [content, setContent] = useState<Content>();
  const [error, setError] = useState("");
  const log = path.endsWith(".log");
  useEffect(() => {
    let active = true;
    let offset = 0;
    setContent(undefined);
    setError("");
    const cancel = poll(
      async () => {
        try {
          const value = await api.material(path, log && live ? offset : 0);
          if (active) {
            offset = value.next_offset;
            setContent((previous) =>
              log && live && value.offset > 0 && previous
                ? { ...value, text: previous.text + value.text }
                : value,
            );
            setError("");
          }
        } catch (error) {
          if (active) setError(String(error));
        }
      },
      live ? 700 : 0,
    );
    return () => {
      active = false;
      cancel();
    };
  }, [path, live, log]);
  const more = async () => {
    if (!content) return;
    try {
      const next = await api.material(path, content.next_offset);
      setContent({ ...next, text: content.text + next.text });
    } catch (error) {
      setError(String(error));
    }
  };
  return (
    <>
      {error && <p role="alert">{error}</p>}
      {!content && !error && <p role="status">读取材料…</p>}
      {content && (
        <>
          {log || !/\.md$/i.test(path) ? (
            <pre className="plain-output">{content.text || "尚无输出"}</pre>
          ) : (
            <div className="markdown">
              <Markdown
                remarkPlugins={[remarkGfm]}
                skipHtml
                components={{
                  code: ({ className, children }) => (
                    <code className={className}>
                      {className?.startsWith("language-")
                        ? String(children)
                            .split(
                              /("[^"\n]*"|'[^'\n]*'|\b(?:def|class|return|import|from|if|else|for|while|const|let|function|true|false|None|True|False)\b)/g,
                            )
                            .map((part, index) => (
                              <span
                                key={index}
                                className={
                                  /^['"]/.test(part)
                                    ? "code-string"
                                    : /^(def|class|return|import|from|if|else|for|while|const|let|function|true|false|None|True|False)$/.test(
                                          part,
                                        )
                                      ? "code-keyword"
                                      : undefined
                                }
                              >
                                {part}
                              </span>
                            ))
                        : children}
                    </code>
                  ),
                  img: ({ alt }) => <span>[图片：{alt}]</span>,
                  a: ({ href, children }) => {
                    if (!href) return <span>{children}</span>;
                    if (/^https?:\/\//i.test(href))
                      return (
                        <a href={href} target="_blank" rel="noreferrer">
                          {children}
                        </a>
                      );
                    if (/^[a-z]+:/i.test(href) || href.startsWith("//"))
                      return <span>{children}</span>;
                    return (
                      <button
                        className="text-link"
                        onClick={() => {
                          const parent = path.slice(
                            0,
                            path.lastIndexOf("/") + 1,
                          );
                          onOpen(
                            decodeURIComponent(
                              href.startsWith("/")
                                ? href
                                : parent + href.split("#")[0],
                            ),
                          );
                        }}
                      >
                        {children}
                      </button>
                    );
                  },
                }}
              >
                {content.text}
              </Markdown>
            </div>
          )}
          {content.more && !live && <button onClick={more}>读取更多</button>}
        </>
      )}
    </>
  );
}
function Trace({ topic, step, path }: { topic: string; step: number; path: string }) {
  const initialRole = Object.keys(roles).find(role => path.endsWith(`.${role}.log`)) as Role | undefined;
  const [role, setRole] = useState<Role>(initialRole || 'expert');
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [log, setLog] = useState('');
  const [diagnostic, setDiagnostic] = useState('');
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true, stream: string | null = null, seq = 0, offset = 0;
    let collected: AgentEvent[] = [], text = '';
    setEvents([]); setLog(''); setLoaded(false); setError(''); setDiagnostic('');
    const logPath = path.slice(0, path.lastIndexOf('/') + 1) + `.${role}.log`;
    const cancel = poll(async () => {
      try {
        let more = true;
        while (active && more) {
          const batch = await api.events(topic, step, role, seq, stream);
          if (!active) return;
          if (batch.reset) { collected = []; text = ''; offset = 0; }
          stream = batch.stream; seq = batch.next_seq;
          collected = [...collected, ...batch.events]; more = batch.more;
          setEvents(collected); setLog(text); setDiagnostic(batch.diagnostic || ''); setLoaded(true);
        }
        try {
          const chunk = await api.material(logPath, offset);
          if (!active) return;
          // A replacement during the log request invalidates that response too.
          const check = await api.events(topic, step, role, seq, stream);
          if (!active) return;
          if (check.reset) return;
          text = chunk.offset > 0 ? text + chunk.text : chunk.text;
          offset = chunk.next_offset; setLog(text);
        } catch (failure) {
          if (!String(failure).includes('Material not found')) throw failure;
        }
        setError('');
      } catch (failure) { if (active) setError(String(failure)); }
    }, 700);
    return () => { active = false; cancel(); };
  }, [topic, step, role, path]);
  return <section aria-label="执行 Trace 内容">
    <label>调用角色 <select aria-label="Trace 角色" value={role} onChange={event => setRole(event.target.value as Role)}>
      {Object.entries(roles).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select></label>
    <p className="muted">进程结果不代表研究产物已提交；仅保留各角色最近一次调用。</p>
    {error && <p role="alert">{error}</p>}
    {diagnostic && <p role="alert">Trace 不完整：{diagnostic}</p>}
    {loaded && !events.length && !diagnostic && <p>此调用无结构化事件</p>}
    <ol aria-label="调用事件">{events.map(event => <li key={event.seq}>
      <strong>{event.title}</strong> · {event.status} <time>{event.ts}</time>
      {event.detail && <p>{event.detail}</p>}
    </li>)}</ol>
    {loaded && events.length > 0 && !events.some(event => ['completed', 'failed', 'timed_out', 'cancelled'].includes(event.title)) &&
      <p className="muted">尚无终止事件：调用可能仍在运行，或 Trace 不完整。</p>}
    <h3>原始日志</h3><pre className="plain-output" aria-label="Trace 原始日志">{log || '尚无输出'}</pre>
  </section>;
}
function Controls({ detail }: { detail: TopicDetail }) {
  const [pending, setPending] = useState("");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [rounds, setRounds] = useState("");
  const [feedback, setFeedback] = useState("");
  useEffect(() => setFeedback(""), [detail.current_round]);
  const [debug, setDebug] = useState(detail.debug_probes || false);
  useEffect(
    () => setDebug(detail.debug_probes || false),
    [detail.debug_probes],
  );
  const active =
    detail.activity === "running" || detail.activity === "stopping";
  const exhausted = detail.status === "BUDGET_EXHAUSTED";
  const submit = async (action: "stop" | "resume" | "revise") => {
    setPending(action);
    setFailure("");
    setMessage("");
    try {
      if (action === "stop" && detail.execution) {
        await api.stop(detail.topic, detail.execution.id);
        setMessage("停止请求已处理；执行活动以服务端状态为准。");
      } else if (action === "revise") {
        await api.revise(detail.topic, feedback);
        setFeedback("");
        setMessage("重拟请求已接收；专家调整后会再次停下。");
      } else {
        await api.resume(
          detail.topic,
          rounds ? Number(rounds) : undefined,
          debug,
        );
        setMessage("继续请求已接收；请查看执行活动和结果。");
      }
    } catch (error) {
      setFailure(String(error));
    } finally {
      setPending("");
    }
  };
  return (
    <section aria-label="专题控制">
      {detail.status !== "COMPLETED" && (
        <>
          <label>
            <input
              type="checkbox"
              aria-label="探针断点调试"
              checked={debug}
              onChange={(event) => setDebug(event.target.checked)}
              disabled={active || !!pending}
            />
            探针断点调试
          </label>
          <label>
            追加轮数{" "}
            <input
              aria-label="追加轮数"
              type="number"
              min="1"
              step="1"
              value={rounds}
              onChange={(event) => setRounds(event.target.value)}
              disabled={active || !!pending}
            />
          </label>
          <button
            disabled={
              active ||
              !!pending ||
              (exhausted && !rounds) ||
              (!!rounds &&
                (!Number.isInteger(Number(rounds)) || Number(rounds) <= 0))
            }
            onClick={() => submit("resume")}
          >
            {rounds
              ? "追加并继续"
              : detail.status === "BLOCKED"
                ? "条件已补齐，继续"
                : debug && !detail.debug_probes
                  ? "启用调试并继续"
                  : !debug && detail.debug_probes
                    ? "关闭调试并自动继续"
                    : detail.probe_breakpoint
                      ? "执行当前探针并继续"
                      : "继续"}
          </button>
          {detail.debug_probes && detail.next_action === "executor" && (
            <div>
              <label>
                当前探针方向意见
                <textarea
                  aria-label="当前探针方向意见"
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                  disabled={active || !!pending}
                />
              </label>
              <button
                disabled={active || !!pending || !feedback.trim()}
                onClick={() => submit("revise")}
              >
                提交意见并重拟
              </button>
              <p className="muted">
                只调整当前探针，由专家设计具体方案；修改专题目标请使用讨论入口。
              </p>
            </div>
          )}
          {exhausted && <p>轮数已耗尽，请追加预算后继续。</p>}
        </>
      )}
      {detail.execution && (
        <button
          disabled={!!pending || detail.activity === "stopping"}
          onClick={() => submit("stop")}
        >
          停止
        </button>
      )}
      {detail.status === "COMPLETED" && <p>研究已完成，不能自动重开。</p>}
      {pending && (
        <p role="status">
          {pending === "stop"
            ? "停止请求处理中，等待确认进程树结束…"
            : pending === "revise"
              ? "重拟请求处理中，等待工程执行权…"
              : "继续请求处理中，等待工程执行权…"}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {failure && <p role="alert">{failure}</p>}
    </section>
  );
}
export default function App() {
  const [overview, setOverview] = useState<Overview>();
  const [topic, setTopic] = useState(
    new URLSearchParams(location.search).get("topic") || "",
  );
  const [detail, setDetail] = useState<TopicDetail>();
  const [navOpen, setNavOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const drawer = useRef<HTMLElement | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [material, setMaterial] = useState("");
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const [theme, setTheme] = useState(
    localStorage.getItem("archa-theme") || "system",
  );
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === "system" ? (media.matches ? "dark" : "light") : theme;
    };
    apply();
    media.addEventListener("change", apply);
    localStorage.setItem("archa-theme", theme);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  useEffect(
    () =>
      poll(async () => {
        try {
          const value = await api.topics();
          setOverview(value);
          setTopic((current) => current || value.topics[0]?.topic || "");
        } catch (error) {
          setError(String(error));
        }
      }, 2000),
    [],
  );
  useEffect(() => {
    setDetail(undefined);
    setMaterial("");
    setDrawerOpen(false);
    if (!topic) return;
    history.replaceState(null, "", "?" + new URLSearchParams({ topic }));
    let active = true;
    const cancel = poll(async () => {
      try {
        const value = await api.topic(topic);
        if (active) {
          setDetail(value);
          setError("");
        }
      } catch (error) {
        if (active) setError(String(error));
      }
    }, 700);
    return () => {
      active = false;
      cancel();
    };
  }, [topic]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const execution = detail?.execution;
  const close = () => {
    setDrawerOpen(false);
    opener.current?.focus();
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) setMaterial("");
  };
  const open = (path: string) => {
    if (!drawerOpen) opener.current = document.activeElement as HTMLElement;
    setTraceOpen(false);
    setMaterial(path);
    setCopied(false);
    setDrawerOpen(true);
  };
  useEffect(() => {
    if (drawerOpen) drawer.current?.focus();
  }, [drawerOpen]);
  const preview = (value: Excerpt) => (
    <>
      <h3>{value.title}</h3>
      <p>{value.empty ? "暂无内容（正文为空）" : value.text}</p>
      <small className="muted">
        原文摘录{value.truncated || value.title_truncated ? " · 已截断" : ""}
      </small>
    </>
  );
  const card = (item: Material | undefined, name: string) =>
    item ? (
      <button className="excerpt" onClick={() => open(item.path)}>
        <span className="source">{item.name}</span>
        {item.excerpt && preview(item.excerpt)}
      </button>
    ) : (
      <p className="muted">
        {name} · {name === "result.md" ? "尚未提交" : "材料缺失"}
      </p>
    );
  return (
    <>
      <a className="skip-link" href="#main">
        跳至内容
      </a>
      <header>
        <div>
          <strong>ArcHa</strong> <span>探索工作台</span>{" "}
          {overview?.demo && <span className="badge">离线演示</span>}
        </div>
        <label>
          主题{" "}
          <select
            aria-label="主题"
            value={theme}
            onChange={(event) => setTheme(event.target.value)}
          >
            <option value="system">跟随系统</option>
            <option value="light">浅色</option>
            <option value="dark">深色</option>
          </select>
        </label>
      </header>
      <button
        className="nav-toggle"
        aria-expanded={navOpen}
        onClick={() => setNavOpen(!navOpen)}
      >
        专题导航
      </button>
      <aside
        className={`topic-nav ${navOpen ? "expanded" : ""}`}
        aria-label="专题导航"
      >
        <h2>探索专题</h2>
        {overview?.topics.map((item) => (
          <button
            key={item.topic}
            aria-current={topic === item.topic ? "page" : undefined}
            onClick={() => {
              setTopic(item.topic);
              setNavOpen(false);
            }}
          >
            {item.topic}
          </button>
        ))}
      </aside>
      <main id="main">
        <div className="heading">
          <div>
            <p>{overview?.project}</p>
            <h1>{topic || "探索专题"}</h1>
          </div>
          <label>
            选择专题{" "}
            <select
              aria-label="选择专题"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
            >
              {overview?.topics.map((item) => (
                <option key={item.topic} value={item.topic}>
                  {item.topic}
                  {item.error ? " · 读取错误" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        {error && <p role="alert">{error}</p>}
        {overview?.topics.length === 0 && (
          <p>尚无专题。请先使用 CLI 初始化专题。</p>
        )}
        {detail && (
          <>
            <section aria-label="专题与执行状态" className="status-panel">
              <p>
                专题状态 <strong>{detail.status}</strong> · 已完成{" "}
                {detail.completed_rounds} / {detail.max_rounds} 轮
              </p>
              <p>
                执行活动{" "}
                <strong>{activities[detail.activity || "unknown"]}</strong>
                {detail.publishing && " · 成果提交中"}
              </p>
              {detail.probe_breakpoint && <p>探针断点等待</p>}
              {execution && (
                <p>
                  {roles[execution.role]} · 第 {execution.round} 轮 · 开始{" "}
                  <time dateTime={execution.started_at}>
                    {new Date(execution.started_at).toLocaleString()}
                  </time>{" "}
                  · 持续{" "}
                  {Math.max(
                    0,
                    Math.floor((now - Date.parse(execution.started_at)) / 1000),
                  )}{" "}
                  秒
                </p>
              )}
              {detail.error && <p role="alert">最近错误：{detail.error}</p>}
            </section>
            {overview?.control && <Controls key={topic} detail={detail} />}
            <section aria-label="目标">
              <h2>探索目标</h2>
              {card(
                detail.materials.find((item) => item.name === "GOAL.md"),
                "GOAL.md",
              )}
            </section>
            <section aria-label="认知状态">
              <h2>当前认知状态</h2>
              <p className="muted">STATE.md 是当前认知，不是历史轮次快照。</p>
              {(() => {
                const state = detail.materials.find(
                  (item) => item.name === "STATE.md",
                );
                return state ? (
                  <>
                    <button onClick={() => open(state.path)}>
                      STATE.md · 阅读原件
                    </button>
                    {state.sections?.length
                      ? state.sections.map((section, index) => (
                          <div key={index} className="state-section">
                            {preview(section)}
                          </div>
                        ))
                      : state.excerpt && preview(state.excerpt)}
                  </>
                ) : (
                  <p>STATE.md · 材料缺失</p>
                );
              })()}
              {detail.materials
                .filter((item) => !["GOAL.md", "STATE.md"].includes(item.name))
                .map((item) => (
                  <button key={item.path} onClick={() => open(item.path)}>
                    {item.name}
                  </button>
                ))}
            </section>
            <div aria-label="探索轮次">
              {[...detail.rounds].reverse().map((item) => (
                <section
                  key={item.number}
                  aria-label={
                    item.number === detail.current_round && !item.completed
                      ? "当前探针"
                      : `第 ${item.number} 轮`
                  }
                >
                  <h2>
                    第 {item.number} 轮 ·{" "}
                    {item.completed ? "结果已提交" : "待执行探针"}
                  </h2>
                  {card(
                    item.materials.find((value) => value.name === "probe.md"),
                    "probe.md",
                  )}
                  {card(
                    item.materials.find((value) => value.name === "result.md"),
                    "result.md",
                  )}
                  <div className="material-buttons">
                    {item.materials
                      .filter(
                        (value) =>
                          !["probe.md", "result.md"].includes(value.name),
                      )
                      .map((value) => (
                        <button
                          key={value.path}
                          onClick={() => open(value.path)}
                        >
                          {value.name}
                        </button>
                      ))}
                    {item.logs.map((log) => (
                      <button key={log.path} onClick={() => open(log.path)}>
                        {roles[log.role]} · stdout / stderr
                      </button>
                    ))}
                  </div>
                </section>
              ))}
              {!detail.rounds.length && <p>尚无轮次材料</p>}
            </div>
          </>
        )}
      </main>
      {material && (
        <aside
          ref={drawer}
          id="material-reader"
          className={`reader-drawer ${drawerOpen ? "open" : ""}`}
          role="dialog"
          aria-label="材料阅读"
          aria-hidden={!drawerOpen}
          inert={!drawerOpen}
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              close();
            }
          }}
          onTransitionEnd={(event) => {
            if (event.target === event.currentTarget && !drawerOpen)
              setMaterial("");
          }}
        >
          <div className="drawer-actions">
            <h2>材料阅读</h2>
            <button onClick={close}>关闭材料</button>
          </div>
          <p className="material-path">{material}</p>
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(material);
                setCopied(true);
              } catch (error) {
                setError(String(error));
              }
            }}
          >
            {copied ? "已复制路径" : "复制路径"}
          </button>
          {/\/steps\/step-([0-9]+)\//.test(material) && <details open={traceOpen} onToggle={event => setTraceOpen(event.currentTarget.open)}>
            <summary>执行 Trace</summary>
            {traceOpen && <Trace topic={topic} step={Number(material.match(/\/step-([0-9]+)\//)![1])} path={material} />}
          </details>}
          {!(traceOpen && material.endsWith('.log')) && <Reader
            path={material}
            onOpen={open}
            live={material.endsWith(".log")}
          />}
        </aside>
      )}
    </>
  );
}
