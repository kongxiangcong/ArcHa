/** Sequential polling: no overlapping reads, bounded requests, immediate reconnect. */
export function poll(read: () => Promise<unknown>, interval: number) {
  let stopped = false,
    pending = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const run = async () => {
    if (stopped || pending) return;
    clearTimeout(timer);
    pending = true;
    try {
      await read();
    } finally {
      pending = false;
      if (!stopped && interval) timer = setTimeout(run, interval);
    }
  };
  const visible = () => {
    if (document.visibilityState === "visible") void run();
  };
  addEventListener("online", run);
  document.addEventListener("visibilitychange", visible);
  void run();
  return () => {
    stopped = true;
    clearTimeout(timer);
    removeEventListener("online", run);
    document.removeEventListener("visibilitychange", visible);
  };
}
