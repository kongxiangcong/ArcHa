"""OS seams: nonblocking writer locks and owned subprocess trees.

No shell is introduced. Windows jobs are assigned while the child is suspended;
failure to establish containment aborts startup. POSIX uses a new session.
Neither mechanism is an OS sandbox against hostile code (e.g. POSIX setsid).
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable
from pathlib import Path


def lock_writer(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            # Windows permits locking a byte beyond EOF. Never truncate this byte.
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError("writer lock is held") from exc
            raise
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_writer(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def command_prefix(binary: str | list[str]) -> list[str]:
    """Explicit argv prefix supports Python/Node CLIs without shell wrappers."""
    if isinstance(binary, str):
        if binary.startswith("["):
            return command_prefix(json.loads(binary))
        if binary.lower().endswith(".py"):
            return [sys.executable, binary]
        return [binary]
    if isinstance(binary, list) and binary and all(isinstance(x, str) and x for x in binary):
        return list(binary)
    raise ValueError("worker binary must be a nonempty string or argv list")


@dataclass
class ExecutionControl:
    """One call's process boundary; each concurrent worker installs its own scope."""
    check: Callable[[], str | None]
    log_dir: Path
    cancelled: str | None = None
    unknown: str | None = None

    def record(self, process, state: str) -> None:
        from .model import write_json
        write_json(self.log_dir / "process.json", {
            "pid": process.pid, "state": state, "returncode": process.returncode,
            "cancel_reason": process.cancel_reason, "termination_error": self.unknown})


_EXECUTION: ContextVar[ExecutionControl | None] = ContextVar("opc_execution", default=None)


@contextmanager
def execution_control(check: Callable[[], str | None], log_dir: Path):
    scope = ExecutionControl(check, log_dir)
    token = _EXECUTION.set(scope)
    try:
        yield scope
    finally:
        _EXECUTION.reset(token)


class Process(subprocess.Popen):
    """Popen with tree ownership; use as a context manager even on success."""

    def __init__(self, argv, **kwargs):
        self._job = None
        self._control = _EXECUTION.get()
        self.cancel_reason = None
        if self._control is not None:
            reason = self._control.check()
            if reason:
                self._control.cancelled = reason
                raise OSError("execution cancelled before process startup: " + reason)
        if os.name == "nt":
            executable = shutil.which(argv[0]) or argv[0]
            if executable.lower().endswith((".cmd", ".bat")):
                raise OSError("batch wrappers are not safe argv executables; configure the "
                              "native .exe or an explicit [node/python, script] binary prefix")
            from .windows import Job
            self._job = Job()
            kwargs["creationflags"] = 0x00000004  # CREATE_SUSPENDED
        else:
            kwargs["start_new_session"] = True
        try:
            super().__init__(argv, **kwargs)
            if self._job is not None:
                self._job.attach_and_resume(self)
            if self._control is not None:
                self._control.record(self, "running")
        except BaseException:
            if getattr(self, "pid", None) is not None:
                self.kill()
                self.wait()
            if self._job is not None:
                self._job.close()
            raise

    def wait(self, timeout=None):
        if self._control is None:
            return super().wait(timeout=timeout)
        deadline = time.monotonic() + timeout if timeout is not None else None
        while self.poll() is None:
            reason = self._control.check()
            if reason:
                self.cancel_reason = self._control.cancelled = reason
                if self._job is not None:
                    self._job.terminate()
                else:
                    try:
                        os.killpg(self.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    super().wait(timeout=.2)
                except subprocess.TimeoutExpired:
                    self.kill_tree()
                self._control.record(self, "cancelled")
                return self.returncode
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(self.args, timeout)
            try:
                super().wait(timeout=min(.05, remaining) if remaining is not None else .05)
            except subprocess.TimeoutExpired:
                continue
        self._control.record(self, "cancelled" if self.cancel_reason else "completed")
        return self.returncode

    def communicate(self, input=None, timeout=None):
        # Popen's file-output communicate delegates to wait; PIPE output needs
        # bounded communicate retries as well, preserving its buffered bytes.
        if self._control is None or (self.stdout is None and self.stderr is None):
            return super().communicate(input, timeout=timeout)
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(self.args, timeout)
            try:
                return super().communicate(input, timeout=min(.05, remaining) if remaining is not None else .05)
            except subprocess.TimeoutExpired:
                input = None
                if self._control.check():
                    self.wait()
                    return super().communicate(timeout=2)

    def kill_tree(self):
        try:
            if self._job is not None:
                self._job.terminate()
            else:
                try:
                    os.killpg(self.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            # A bounded wait leaves an unverifiable termination without a Call
            # receipt, so recovery keeps its workspace and blocks redispatch.
            super().wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if self._control is not None:
                self._control.unknown = str(exc)
                self._control.record(self, "unknown")
            raise
        if self._control is not None:
            self._control.record(self, "cancelled" if self.cancel_reason else "completed")

    def __exit__(self, *args):
        try:
            self.kill_tree()
        finally:
            if self._job is not None:
                self._job.close()
            super().__exit__(*args)


def portable_path(path: str) -> bool:
    """Contract paths are Git-style relative names on every host."""
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return False
    parts = path.rstrip("/").split("/")
    reserved = {"con", "prn", "aux", "nul", *('com%d' % i for i in range(1, 10)),
                *('lpt%d' % i for i in range(1, 10))}
    return all(p not in ("", ".", "..") and not p.endswith((" ", "."))
               and p.split(".", 1)[0].casefold() not in reserved for p in parts)


def is_link(path: Path) -> bool:
    """Include Windows junctions/reparse points, also on Python 3.10."""
    import stat
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)
