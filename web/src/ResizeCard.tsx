import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
/** Measured height adapter for transitions.dev 01-card-resize. */
export function ResizeCard({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const [height, setHeight] = useState(0);
  const body = useRef<HTMLDivElement>(null);
  const id = useId();
  useLayoutEffect(() => {
    const element = body.current;
    if (!element) return;
    const observer = new ResizeObserver(
      () =>
        element.getClientRects().length &&
        setHeight(element.getBoundingClientRect().height),
    );
    if (element.getClientRects().length)
      setHeight(element.getBoundingClientRect().height);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <section className="result-card">
      <button
        className="link-button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        {title} · {open ? "收起" : "展开"}
      </button>
      <div
        id={id}
        className="t-resize"
        inert={!open}
        aria-hidden={!open}
        style={{ height: open ? height : 0, overflow: "hidden" }}
      >
        <div ref={body}>{children}</div>
      </div>
    </section>
  );
}
