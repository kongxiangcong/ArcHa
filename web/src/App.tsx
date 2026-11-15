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
                <strong>{activities[detail.activity || "unknown"]}</strong>
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
            <div className="workspace-grid">
              <section>
                <h2>当前认知状态</h2>
                <p className="muted">STATE.md 是当前认知，不是历史轮次快照。</p>
                {currentState && (
                  <Reader path={currentState.path} onOpen={open} live />
                )}
              </section>
              <section>
                <h2>轮次材料</h2>
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
                      {selected.materials.map((item) => (
                        <button key={item.path} onClick={() => open(item.path)}>
                          {item.name}
                        </button>
                      ))}
                    </div>
                    {selected.logs.map((log) => (
                      <details key={log.path} open>
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
              </section>
            </div>
            <section>
              <h2>专题材料</h2>
              <div className="material-buttons">
                {detail.materials.map((item) => (
                  <button key={item.path} onClick={() => open(item.path)}>
                    {item.name === "STATE.md" ? "当前 STATE.md" : item.name}
                  </button>
                ))}
              </div>
            </section>
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
