import { ResizeCard } from "./ResizeCard";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { poll } from "./poll";
import { enc, get, useResource } from "./api";
import { Alert, label } from "./components";
import type { Material, InspectionData, Content, Envelope } from "./types";

export function Inspection({
  run,
  attempt,
  call,
  onCall,
  onOpen,
  revision = "",
}: {
  run: string;
  attempt: number;
  call: string | null;
  revision?: string;
  onCall: (id: string) => void;
  onOpen: (material: Material, opener: HTMLElement) => void;
}) {
  const resource = useResource<InspectionData>(
    `/runs/${enc(run)}/attempts/${attempt}/inspection${call ? "?call=" + enc(call) : ""}`,
    1500,
    revision,
  );
  const data = resource.value?.data;
  return (
    <section className="detail-section handoff">
      <h3>调用与交接</h3>
      <Alert error={resource.error} stale={!!data} />
      {data && (
        <>
          <label className="call-selector">
            选择工作调用
            <select
              aria-label="选择工作调用"
              value={data.call_id ?? ""}
              onChange={(event) => onCall(event.target.value)}
            >
              {data.calls.map((item, index) => (
                <option key={item.id} value={item.id}>
                  {label(item.role)} · 调用 {index + 1} · {label(item.state)}
                </option>
              ))}
            </select>
          </label>
          {data.error && <p className="call-error">{data.error}</p>}
          <p className="muted">{data.input_note}</p>
          {data.input && (
            <div className="handoff-input">
              <h4>传入内容</h4>
              {data.input.title && <p>{data.input.title}</p>}
              {data.input.goal && <p>{data.input.goal}</p>}
              {data.input.purpose && <p>{data.input.purpose}</p>}
              {data.input.hypothesis && <p>{data.input.hypothesis}</p>}
            </div>
          )}
          {data.output?.summary && (
            <ResizeCard title="记录的输出">
              <p>{data.output.summary}</p>
            </ResizeCard>
          )}
          <h4>任务文件与产出</h4>
          {!data.materials.length && (
            <p className="muted">本次调用没有可确认的任务材料。</p>
          )}
          {data.materials.map((material) => (
            <div className="material-entry" key={material.id}>
              <button
                className="link-button"
                disabled={material.availability !== "available"}
                onClick={(event) => onOpen(material, event.currentTarget)}
              >
                {material.name}
              </button>
              <span className="muted">{material.note ?? material.purpose}</span>
            </div>
          ))}
          {data.material_note && <p className="muted">{data.material_note}</p>}
        </>
      )}
    </section>
  );
}

export function MaterialReader({
  material,
  onClose,
}: {
  material: Material;
  onClose: () => void;
}) {
  const [state, setState] = useState<{
    id: string;
    pages: Content[];
    error?: string;
    pending: boolean;
  }>({ id: material.id, pages: [], pending: true });
  const heading = useRef<HTMLHeadingElement>(null);
  const pagesRef = useRef<Content[]>([]);
  const busy = useRef(false);
  const alive = useRef(true);
  async function read(offset = 0) {
    if (busy.current) return;
    busy.current = true;
    setState((old) => ({ ...old, pending: true, error: undefined }));
    try {
      const value: Envelope<Content> = await get(
        `/artifacts/${enc(material.id)}/content?offset=${offset}&limit=65536`,
      );
      if (!alive.current) return;
      if (
        offset &&
        pagesRef.current[0]?.content_version !== value.data.content_version
      ) {
        throw new Error("内容已更新，正在重新读取当前版本");
      }
      pagesRef.current = offset
        ? [...pagesRef.current, value.data]
        : [value.data];
      setState((old) =>
        old.id === material.id
          ? {
              id: material.id,
              pages: offset ? [...old.pages, value.data] : [value.data],
              pending: false,
            }
          : old,
      );
    } catch (error) {
      if (!alive.current) return;
      setState((old) => ({
        ...old,
        error: (error as Error).message,
        pending: false,
      }));
    } finally {
      busy.current = false;
    }
  }
  useEffect(() => {
    alive.current = true;
    const stop = poll(async () => {
      // Re-read only the already opened extent, never mix pages from different versions.
      const count = Math.max(1, pagesRef.current.length);
      if (busy.current) return;
      busy.current = true;
      try {
        const pages: Content[] = [];
        let offset = 0;
        for (let i = 0; i < count; i++) {
          const value = await get<Content>(
            `/artifacts/${enc(material.id)}/content?offset=${offset}&limit=65536`,
          );
          if (
            pages.length &&
            pages[0].content_version !== value.data.content_version
          )
            return;
          pages.push(value.data);
          if (value.data.eof) break;
          offset = value.data.next_offset ?? 0;
        }
        if (alive.current) {
          pagesRef.current = pages;
          setState({ id: material.id, pages, pending: false });
        }
      } catch (error) {
        if (alive.current)
          setState((old) => ({
            ...old,
            error: (error as Error).message,
            pending: false,
          }));
      } finally {
        busy.current = false;
      }
    }, 1500);
    heading.current?.focus();
    return () => {
      alive.current = false;
      stop();
    };
  }, [material.id]);
  const current = state.pages.at(-1),
    content = state.pages.map((page) => page.content).join("");
  return (
    <section className="material-reader t-page-slide" aria-label="任务文件阅读">
      <div className="reader-heading">
        <button className="btn" onClick={onClose}>
          返回工作现场
        </button>
        <h2 tabIndex={-1} ref={heading}>
          {material.name}
        </h2>
        <span className="muted">{material.purpose}</span>
      </div>
      <div className="reader-body" tabIndex={0}>
        <Alert error={state.error} stale={!!content} />
        {material.name.endsWith(".md") ? (
          <div className="task-markdown">
            <ReactMarkdown
              skipHtml
              remarkPlugins={[remarkGfm]}
              components={{ a: () => null, img: () => null }}
            >
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          <pre>{content}</pre>
        )}
        {!current?.eof && !state.error && (
          <button
            className="btn"
            disabled={state.pending}
            onClick={() => void read(current?.next_offset ?? 0)}
          >
            {state.pending ? "读取中" : "继续读取"}
          </button>
        )}
        {state.error && (
          <button
            className="btn"
            onClick={() => void read(current?.next_offset ?? 0)}
          >
            重新读取
          </button>
        )}
      </div>
    </section>
  );
}
