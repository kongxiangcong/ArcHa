import { useId, useRef } from "react";

/** Expanded reading is intentional; native dialog handles Escape and focus return. */
export function SummaryDialog({
  title,
  text,
}: {
  title: string;
  text: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  return (
    <>
      <button
        className="summary-expand"
        onClick={() => dialog.current?.showModal()}
        aria-label={`展开${title}`}
      >
        展开
      </button>
      <dialog className="summary-dialog" ref={dialog} aria-labelledby={id}>
        <header>
          <h2 id={id}>{title}</h2>
          <button
            className="btn"
            autoFocus
            onClick={() => dialog.current?.close()}
          >
            关闭
          </button>
        </header>
        <div className="summary-dialog-copy">
          {text.split(/\n\s*\n/).map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
      </dialog>
    </>
  );
}
