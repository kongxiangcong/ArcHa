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


class Process(subprocess.Popen):
    """Popen with tree ownership; use as a context manager even on success."""

    def __init__(self, argv, **kwargs):
        self._job = None
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
        except BaseException:
            if getattr(self, "pid", None) is not None:
                self.kill()
                self.wait()
            if self._job is not None:
                self._job.close()
            raise

    def kill_tree(self):
        if self._job is not None:
            self._job.terminate()
        else:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.wait()

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
