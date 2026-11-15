import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "./api";
import { poll } from "./poll";
import type { Content, Overview, TopicDetail, Role } from "./types";

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
  const [round, setRound] = useState<number>();
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
    setRound(undefined);
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
  const selected =
    detail?.rounds.find((item) => item.number === round) ||
    detail?.rounds.at(-1);
  const execution = detail?.execution;
  const currentState = detail?.materials.find(
    (item) => item.name === "STATE.md",
  );
  const open = (path: string) => {
    setMaterial(path);
    document.getElementById("material-reader")?.focus();
  };
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
                <strong>
                  {detail.probe_breakpoint
                    ? "探针断点等待"
                    : activities[detail.activity || "unknown"]}
                </strong>
                {detail.publishing && " · 成果提交中"}
              </p>
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
              {detail.error && <p role="alert">{detail.error}</p>}
            </section>
            {overview?.control && <Controls key={topic} detail={detail} />}
            {detail.current_probe && (
              <section aria-label="当前探针">
                <h2>第 {detail.current_round} 轮 · 待执行探针</h2>
                <Reader path={detail.current_probe.path} onOpen={open} live />
              </section>
            )}
            <details>
              <summary>输入与认知状态</summary>
              <p className="muted">STATE.md 是当前认知，不是历史轮次快照。</p>
              <div className="material-buttons">
                {detail.materials
                  .filter((item) => item.name !== "STATE.md")
                  .map((item) => (
                    <button key={item.path} onClick={() => open(item.path)}>
                      {item.name}
                    </button>
                  ))}
              </div>
              {currentState && (
                <Reader path={currentState.path} onOpen={open} live />
              )}
            </details>
            <details>
              <summary>轮次历史与日志</summary>
              <nav aria-label="轮次">
                {detail.rounds.map((item) => (
                  <button
                    key={item.number}
                    aria-pressed={selected?.number === item.number}
                    onClick={() => setRound(item.number)}
                  >
                    第 {item.number} 轮{item.completed ? " · 已完成" : ""}
                  </button>
                ))}
              </nav>
              {selected ? (
                <>
                  <h3>第 {selected.number} 轮</h3>
                  <div className="material-buttons">
                    {selected.materials
                      .filter(
                        (item) => item.path !== detail.current_probe?.path,
                      )
                      .map((item) => (
                        <button key={item.path} onClick={() => open(item.path)}>
                          {item.name}
                        </button>
                      ))}
                  </div>
                  {selected.logs.map((log) => (
                    <details key={log.path}>
                      <summary>{roles[log.role]} · stdout / stderr</summary>
                      <Reader
                        key={execution?.id || "idle"}
                        path={log.path}
                        onOpen={open}
                        live
                      />
                    </details>
                  ))}
                </>
              ) : (
                <p>尚无轮次材料</p>
              )}
            </details>
            <section id="material-reader" tabIndex={-1} aria-label="材料阅读">
              <h2>材料阅读</h2>
              {material ? (
                <>
                  <p className="material-path">{material}</p>
                  <Reader key={material} path={material} onOpen={open} />
                </>
              ) : (
                <p>选择轮次材料或专题材料查看原件。</p>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}
