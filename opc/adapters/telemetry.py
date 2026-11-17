"""Best-effort, per-call observation; never a research state source."""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone


def timestamp():
    now = time.time_ns()
    return datetime.fromtimestamp(now // 1_000_000_000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + f'.{now % 1_000_000_000:09d}Z'


class Telemetry:
    def __init__(self, log_file, role, provider):
        self.log_file = log_file
        self.path = log_file.with_suffix('.events.jsonl')
        self.published = False
        self.diagnostic = None
        self.seq = 0
        self.stream = None
        self.finished = False
        self.started = time.monotonic()
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
            self.stream = os.fdopen(fd, 'w', encoding='utf-8')
            self.event('started', 'running', f'role={role}; provider={provider}')
            if self.stream is not None:
                os.replace(temporary, self.path)
                self.published = True
        except OSError as exc:
            self.failure(exc)
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError as exc:
                    self.failure(exc)

    def failure(self, exc):
        if self.finished:
            return
        message = f'Telemetry incomplete: {"unpublished stream: " if not self.published else ""}{self.path.name}: {exc}'
        self.incomplete(message)
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.close()
            except OSError as close_error:
                print(f'{message}; close failed: {close_error}', file=sys.stderr)

    def incomplete(self, message):
        self.diagnostic = message
        print(message, file=sys.stderr)

    def write_diagnostic(self):
        try:
            with self.log_file.open('ab') as log:
                log.write(('\n' + self.diagnostic + '\n').encode('utf-8'))
        except OSError as log_error:
            print(f'{self.diagnostic}; log diagnostic failed: {log_error}', file=sys.stderr)

    def event(self, title, status, detail=None, kind='lifecycle'):
        if self.stream is None:
            return
        self.seq += 1
        try:
            self.stream.write(json.dumps(dict(seq=self.seq, ts=timestamp(), kind=kind,
                                             title=title, status=status, detail=detail), ensure_ascii=False) + '\n')
            self.stream.flush()
        except OSError as exc:
            self.failure(exc)

    def finish(self, outcome, code=None, context=None):
        self.event(outcome, 'ok' if outcome == 'completed' else 'error',
                   f'exit_code={code}; elapsed_seconds={time.monotonic() - self.started:.3f}' +
                   (f'; {context}' if context else ''))
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError as exc:
                self.failure(exc)
        # Only the invocation owner writes diagnostics to the raw log, after
        # output and observation end, so a late tail cannot write into a retry.
        if self.diagnostic:
            self.write_diagnostic()
        self.finished = True
        self.stream = None
