"""Independent, bounded observation of direct-to-file process output."""
import threading
import time

from .native_events import NativeEvents


class LogTail:
    BATCH = 256 * 1024
    LINE_LIMIT = 1024 * 1024

    def __init__(self, telemetry, provider):
        self.telemetry = telemetry
        self.parser = NativeEvents(provider)
        self.ended = threading.Event()
        self.stopped = threading.Event()
        self.deadline = None
        self.thread = None
        self.error = None
        if provider in ('codex', 'dsh') and telemetry.stream is not None:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def diagnostic(self, message):
        if self.stopped.is_set():
            return
        self.telemetry.event('Trace incomplete', 'error', message, kind='diagnostic')
        self.error = message

    def expired(self):
        return self.deadline is not None and time.monotonic() >= self.deadline

    def line(self, data):
        event = self.parser.parse(data.decode('utf-8'))
        if event and not self.stopped.is_set():
            kind, title, status, detail = event
            self.telemetry.event(title, status, detail, kind=kind)

    def run(self):
        pending = b''
        try:
            with self.telemetry.log_file.open('rb') as source:
                while not self.stopped.is_set() and self.telemetry.stream is not None:
                    if self.expired():
                        return
                    data = source.read(self.BATCH)
                    if not data:
                        if self.ended.is_set():
                            if pending:
                                self.line(pending)
                            return
                        self.ended.wait(.2)
                        continue
                    lines = data.split(b'\n')
                    if len(pending) + len(lines[0]) > self.LINE_LIMIT:
                        raise ValueError('native log line exceeds 1 MiB parsing limit')
                    lines[0] = pending + lines[0]
                    pending = lines.pop()
                    for line in lines:
                        if self.stopped.is_set() or self.expired():
                            return
                        if len(line) > self.LINE_LIMIT:
                            raise ValueError('native log line exceeds 1 MiB parsing limit')
                        self.line(line)
                    if len(pending) > self.LINE_LIMIT:
                        raise ValueError('native log line exceeds 1 MiB parsing limit')
                    if not self.ended.is_set():
                        self.ended.wait(.2)
        except Exception as exc:
            self.diagnostic(f'native event extraction: {exc}')

    def finish(self):
        if self.thread is None:
            return
        self.deadline = time.monotonic() + 2
        self.ended.set()
        self.thread.join(2)
        expired = self.thread.is_alive() or self.expired()
        self.stopped.set()
        if expired:
            self.error = 'log tail exceeded 2 second finalization budget'
            self.telemetry.event('Trace incomplete', 'error', self.error, kind='diagnostic')
        if self.error:
            self.telemetry.incomplete(f'Telemetry incomplete: {self.error}')
