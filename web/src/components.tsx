import { useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ReactFlow,
  Background,
  Controls,
  Position,
  type Node,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  AuiProvider,
  AuiConfig,
  Tools,
  DataRenderers,
  ReadonlyThreadProvider,
  ThreadPrimitive,
  MessagePrimitive,
  fromThreadMessageLike,
  type ThreadMessageLike,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import type {
  Fact,
  Issue,
  Meta,
  State,
  Task,
  Requirement,
  Metric,
  MessageItem,
} from "./types";
export const labels: Record<string, string> = {
  available: "可读取",
  partial: "部分记录",
  missing: "未发现记录",
  unreadable: "不可读取",
  unsupported: "暂不支持",
  unknown: "未确认",
  unverified: "未验证",
  met: "满足",
  not_met: "未满足",
  pending_review: "待审阅",
  not_applicable: "不适用",
  not_evaluated: "未验收",
  passed: "通过",
  failed: "未通过",
  running: "记录中运行，实时状态未确认",
  active: "记录中活动，实时状态未确认",
  finished: "已结束",
  not_started: "未开始",
  cancelled: "已取消",
  paused: "记录中暂停",
  blocked: "受阻",
  ready: "准备就绪",
  draft: "草稿",
  ready_for_onboard: "可接入",
  preparing: "准备中",
  verified: "关系已核对",
  unresolved: "未关联",
  ambiguous: "关联存在歧义",
  digest_mismatch: "摘要不一致",
  automated: "自动验证",
  review: "审阅",
  complete: "完整",
  comparable: "可比较",
  not_comparable: "范围不同，不能直接比较",
  recorded: "来源记录",
  derived: "规则投影",
  live: "项目数据",
  demo: "演示数据",
  snapshot: "历史快照",
};
export function label(value: string | null | undefined) {
  return value ? (labels[value] ?? `${value}（暂未识别）`) : "未记录";
}
export function time(value: string | null | undefined) {
  return value
    ? new Date(value).toLocaleString(undefined, { hour12: false })
    : "未记录";
}
export function Badge({ value }: { value: string | null | undefined }) {
  return (
    <span
      className={`badge ${["met", "passed", "ready", "verified", "available"].includes(value ?? "") ? "good" : ["failed", "not_met", "ambiguous", "digest_mismatch", "partial", "blocked"].includes(value ?? "") ? "warn" : ""}`}
    >
      {label(value)}
    </span>
  );
}
export function StateView({ title, state }: { title: string; state?: State }) {
  return (
    <div className="state">
      <span className="muted">{title}</span>
      <strong>{label(state?.value)}</strong>
      <small title={state?.at ?? ""}>
        {state ? `${label(state.basis)} · ${time(state.at)}` : "未发现记录"}
      </small>
      {state?.raw_value && state.value === "unknown" && (
        <small>原值：{state.raw_value}</small>
      )}
      {state?.note && <small>{state.note}</small>}
    </div>
  );
}
export function Problems({ issues = [] }: { issues?: Issue[] }) {
  return issues.length ? (
    <details className="issues">
      <summary>来源提示 · {issues.length}</summary>
      <ul>
        {issues.map((i, n) => (
          <li key={`${i.code}-${n}`}>
            <code>{i.code}</code> {i.message}
          </li>
        ))}
      </ul>
    </details>
  ) : null;
}
export function Sources({
  meta,
  onArtifact,
}: {
  meta?: Meta;
  onArtifact: (id: string) => void;
}) {
  return meta ? (
    <>
      <Problems issues={meta.issues} />
      <details className="sources">
        <summary>来源与可用性 · {label(meta.availability)}</summary>
        {meta.source_refs?.map((s, n) => (
          <p key={n} className="path">
            {s.display_path} {s.locator}
            {s.artifact_id && (
              <button
                className="link"
                onClick={() => onArtifact(s.artifact_id!)}
              >
                查看来源
              </button>
            )}
          </p>
        ))}
      </details>
    </>
  ) : null;
}
export function SafeMarkdown({
  children,
  onArtifact,
  onTask,
  links,
  targets,
}: {
  children: string;
  onArtifact?: (id: string) => void;
  onTask?: (id: string) => void;
  links?: Record<string, string>;
  targets?: Record<string, { kind: string; id: string }>;
}) {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h3>{children}</h3>,
          h2: ({ children }) => <h4>{children}</h4>,
          img: ({ alt }) => (
            <span className="muted">[外部图片未自动加载：{alt || "图片"}]</span>
          ),
          a: ({ href, children }) => {
            if (href && targets?.[href])
              return (
                <button
                  className="link"
                  onClick={() =>
                    targets[href].kind === "task"
                      ? onTask?.(targets[href].id)
                      : onArtifact?.(targets[href].id)
                  }
                >
                  {children}
                </button>
              );
            if (href && links?.[href])
              return (
                <button className="link" onClick={() => onTask?.(links[href])}>
                  {children}
                </button>
              );
            if (href?.startsWith("artifact:"))
              return (
                <button
                  className="link"
                  onClick={() => onArtifact?.(href.slice(9))}
                >
                  {children}
                </button>
              );
            if (href?.startsWith("task:"))
              return (
                <button
                  className="link"
                  onClick={() => onTask?.(href.slice(5))}
                >
                  {children}
                </button>
              );
            return href && /^(https?:|mailto:|#)/.test(href) ? (
              <a
                href={href}
                target={href.startsWith("#") ? undefined : "_blank"}
                rel="noopener noreferrer"
              >
                {children}
              </a>
            ) : (
              <span>{children}</span>
            );
          },
          input: (props) => <input {...props} disabled />,
        }}
        urlTransform={(url) =>
          targets?.[url] || links?.[url]
            ? url
            : /^(artifact:|task:)/.test(url)
              ? url
              : /^(https?:|mailto:|#)/.test(url)
                ? url
                : ""
        }
      >
        {children}
      </Markdown>
    </div>
  );
}
export function FactView({
  title,
  fact,
  onArtifact,
}: {
  title: string;
  fact: Fact | null | undefined;
  onArtifact: (id: string) => void;
}) {
  return (
    <div className="fact">
      <dt>{title}</dt>
      <dd>
        {fact?.text ? (
          <>
            <SafeMarkdown onArtifact={onArtifact}>{fact.text}</SafeMarkdown>
            {fact.source_refs
              ?.filter((s) => s.artifact_id)
              .map((s, n) => (
                <button
                  key={n}
                  className="link source-link"
                  onClick={() => onArtifact(s.artifact_id!)}
                >
                  来源 {n + 1}
                </button>
              ))}
          </>
        ) : (
          <span className="muted">未记录</span>
        )}
      </dd>
    </div>
  );
}
export function TaskGraph({
  tasks,
  onTask,
  selected,
}: {
  tasks: Task[];
  onTask: (id: string) => void;
  selected: string;
}) {
  const { nodes, edges } = useMemo(() => {
    const g = new dagre.graphlib.Graph()
      .setGraph({ rankdir: "LR", ranksep: 70, nodesep: 30 })
      .setDefaultEdgeLabel(() => ({}));
    tasks.forEach((t) => g.setNode(t.id, { width: 230, height: 90 }));
    const es = tasks.flatMap((t) =>
      (t.depends_on || []).flatMap((d) => {
        const id = typeof d === "string" ? d : d.id;
        const found = tasks.find(
          (x) => x.id === id || x.research_task_id === id,
        );
        return found
          ? [{ id: `${found.id}>${t.id}`, source: found.id, target: t.id }]
          : [];
      }),
    );
    es.forEach((e) => g.setEdge(e.source, e.target));
    dagre.layout(g);
    return {
      nodes: tasks.map(
        (t) =>
          ({
            id: t.id,
            data: {
              label: (
                <>
                  <strong>{t.title}</strong>
                  <small>{t.research_task_id ?? "直接任务"}</small>
                </>
              ),
            },
            position: { x: g.node(t.id).x - 115, y: g.node(t.id).y - 45 },
            sourcePosition: Position.Right,
            targetPosition: Position.Left,
            selected: t.id === selected,
            style: { width: 230, minHeight: 90 },
          }) as Node,
      ),
      edges: es,
    };
  }, [tasks, selected]);
  return (
    <div className="graph" aria-label="研究任务依赖图">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodeClick={(_, n) => onTask(n.id)}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesReconnectable={false}
        deleteKeyCode={null}
        fitView
        minZoom={0.2}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
export function DataTable<T>({
  data,
  columns,
  caption,
}: {
  data: T[];
  columns: ColumnDef<T>[];
  caption: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filter, setFilter] = useState("");
  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });
  return (
    <section className="table-section">
      <label className="filter">
        筛选{caption}
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="输入关键词"
        />
      </label>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label={caption}
      >
        <table>
          <caption>{caption}</caption>
          <thead>
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id}>
                {g.headers.map((h) => (
                  <th
                    key={h.id}
                    aria-sort={
                      h.column.getIsSorted() === "asc"
                        ? "ascending"
                        : h.column.getIsSorted() === "desc"
                          ? "descending"
                          : "none"
                    }
                  >
                    <button
                      onClick={h.column.getToggleSortingHandler()}
                      disabled={!h.column.getCanSort()}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getIsSorted() === "asc"
                        ? " ↑"
                        : h.column.getIsSorted() === "desc"
                          ? " ↓"
                          : ""}
                    </button>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((r) => (
              <tr key={r.id}>
                {r.getVisibleCells().map((c) => (
                  <td key={c.id}>
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!table.getRowModel().rows.length && (
          <p className="empty">未发现匹配记录</p>
        )}
      </div>
    </section>
  );
}
export function Requirements({
  items,
  onArtifact,
}: {
  items: Requirement[];
  onArtifact: (id: string) => void;
}) {
  const columns = useMemo<ColumnDef<Requirement>[]>(
    () => [
      { accessorKey: "id", header: "要求" },
      { accessorKey: "text", header: "内容" },
      {
        accessorKey: "verification",
        header: "验证方式",
        cell: (c) => label(c.getValue() as string),
      },
      {
        accessorKey: "result",
        header: "已有结果",
        cell: (c) => <Badge value={c.getValue() as string} />,
      },
      {
        accessorKey: "tested_commit",
        header: "所审版本",
        cell: (c) => <code>{(c.getValue() as string) || "未记录"}</code>,
      },
      {
        id: "evidence",
        header: "证据",
        cell: (c) => (
          <>
            {[
              ...new Set(
                [
                  c.row.original.report_artifact_id,
                  ...c.row.original.evidence_refs.map((s) => s.artifact_id),
                ].filter((x): x is string => !!x),
              ),
            ].map((id, n) => (
              <button key={id} className="link" onClick={() => onArtifact(id)}>
                来源 {n + 1}
              </button>
            ))}
          </>
        ),
      },
    ],
    [onArtifact],
  );
  return <DataTable data={items} columns={columns} caption="完成条件" />;
}
export function Metrics({
  items,
  onArtifact,
}: {
  items: Metric[];
  onArtifact: (id: string) => void;
}) {
  const columns = useMemo<ColumnDef<Metric>[]>(
    () => [
      { accessorKey: "name", header: "指标" },
      { accessorKey: "unit", header: "单位" },
      { accessorKey: "direction", header: "方向" },
      { accessorKey: "threshold", header: "阈值" },
      ...["baseline", "candidate", "champion", "selected"].map((key) => ({
        accessorKey: key,
        header: key,
        cell: (c: { getValue: () => unknown }) => (
          <code>
            {c.getValue() == null
              ? "未记录"
              : typeof c.getValue() === "object"
                ? JSON.stringify(c.getValue())
                : String(c.getValue())}
          </code>
        ),
      })),
      {
        id: "scope",
        header: "版本与评价范围",
        cell: (c) => (
          <div>
            {Object.entries(c.row.original.scopes ?? {}).map(([key, value]) => (
              <details key={key}>
                <summary>{key}</summary>
                <pre>{JSON.stringify(value, null, 2)}</pre>
              </details>
            ))}
            {c.row.original.source_refs.map((ref, n) => (
              <div className="path" key={n}>
                {ref.display_path} {ref.locator}
                {ref.artifact_id && (
                  <button
                    className="link"
                    onClick={() => onArtifact(ref.artifact_id!)}
                  >
                    证据
                  </button>
                )}
              </div>
            ))}
          </div>
        ),
      },
      {
        accessorKey: "comparison_state",
        header: "比较范围",
        cell: (c) => label(c.getValue() as string),
      },
    ],
    [],
  );
  return items.length ? (
    <DataTable data={items} columns={columns} caption="已有数值与版本范围" />
  ) : (
    <p className="empty">未记录数值目标或可用测量结果</p>
  );
}
function ToolPart({
  toolName,
  args,
  result,
  isError,
}: ToolCallMessagePartProps) {
  return (
    <details className="tool">
      <summary>
        工具记录 · {toolName}
        {isError ? " · 错误" : ""}
      </summary>
      <pre>{JSON.stringify(args, null, 2)}</pre>
      <strong>已记录结果</strong>
      <pre>
        {result === undefined
          ? "未记录"
          : typeof result === "string"
            ? result
            : JSON.stringify(result, null, 2)}
      </pre>
    </details>
  );
}
function Message() {
  return (
    <MessagePrimitive.Root className="message">
      <MessagePrimitive.Parts
        components={{
          Text: ({ text }) => <SafeMarkdown>{text}</SafeMarkdown>,
          Reasoning: ({ text }) => (
            <details>
              <summary>记录的推理</summary>
              <pre>{text}</pre>
            </details>
          ),
          tools: { Fallback: ToolPart },
          Image: () => <span>图片未自动加载</span>,
          File: () => <span>附件请从产物入口查看</span>,
        }}
      />
    </MessagePrimitive.Root>
  );
}
export function ReadonlyMessages({ items }: { items: MessageItem[] }) {
  const messages = useMemo(
    () =>
      items.map((item) => {
        const payload = (item.payload ?? {}) as Record<string, unknown>;
        const inner = (payload.item ?? payload) as Record<string, unknown>;
        const content: unknown[] = Array.isArray(item.content)
          ? item.content
          : item.kind === "tool_call" || item.kind === "tool_result"
            ? [
                {
                  type: "tool-call",
                  toolCallId: item.tool_call_id ?? item.id,
                  toolName: item.tool_name ?? "unknown",
                  args: inner.arguments ?? {
                    command: inner.command ?? item.text ?? "",
                  },
                  result:
                    item.kind === "tool_result"
                      ? (inner.aggregated_output ?? inner.output ?? item.text)
                      : undefined,
                  isError: !!inner.error,
                },
              ]
            : [
                {
                  type: "text",
                  text:
                    typeof item.content === "string"
                      ? item.content
                      : (item.text ?? JSON.stringify(payload, null, 2)),
                },
              ];
        const safe = content.map((part) => {
          const p = part as Record<string, unknown>;
          if (p.type === "text")
            return { type: "text" as const, text: String(p.text ?? "") };
          if (p.type === "tool-call")
            return {
              type: "tool-call" as const,
              toolCallId: String(p.toolCallId ?? item.id),
              toolName: String(p.toolName ?? "unknown"),
              args: (p.args ?? {}) as Record<string, unknown>,
              argsText: JSON.stringify(p.args ?? {}),
              result: p.result,
              isError: !!p.isError,
            };
          return { type: "text" as const, text: JSON.stringify(p, null, 2) };
        });
        return fromThreadMessageLike(
          {
            id: item.id,
            role:
              item.role === "user"
                ? "user"
                : item.role === "system"
                  ? "system"
                  : "assistant",
            content: safe,
          } as ThreadMessageLike,
          item.id,
          { type: "complete", reason: "unknown" },
        );
      }),
    [items],
  );
  return messages.length ? (
    <>
      {/* Empty renderer scopes only: no tool definitions, executor, composer, or model runtime. */}
      <AuiProvider
        config={AuiConfig({ tools: Tools({}), dataRenderers: DataRenderers() })}
      >
        <ReadonlyThreadProvider messages={messages}>
          <ThreadPrimitive.Viewport
            autoScroll={false}
            scrollToBottomOnInitialize={false}
            scrollToBottomOnThreadSwitch={false}
            scrollToBottomOnRunStart={false}
          >
            <ThreadPrimitive.Messages
              components={{
                UserMessage: Message,
                AssistantMessage: Message,
                SystemMessage: Message,
              }}
            />
          </ThreadPrimitive.Viewport>
        </ReadonlyThreadProvider>
      </AuiProvider>
      <details className="sources">
        <summary>原始事件与类型 · {items.length} 条</summary>
        {items.map((item) => (
          <details key={item.id}>
            <summary>
              {String(item.kind ?? item.type ?? "unknown")} ·{" "}
              {String(
                (item.payload as Record<string, unknown>)?.type ?? "未记录类型",
              )}
            </summary>
            <pre>{JSON.stringify(item.payload ?? item, null, 2)}</pre>
          </details>
        ))}
      </details>
    </>
  ) : (
    <p className="empty">未发现可确认归属的调用内容</p>
  );
}
