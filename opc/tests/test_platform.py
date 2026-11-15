"""Real OS process and lock regressions, including Windows Job containment."""
import os
import subprocess
import sys
import time
from pathlib import Path
import pytest
from opc.core.platform import Process, lock_writer, unlock_writer

@pytest.mark.parametrize("parent_exits", [False, True])
def test_process_tree_cleans_grandchildren(tmp_path, parent_exits):
    marker = tmp_path / "escaped.txt"
    ready = tmp_path / "ready.txt"
    grandchild = "import time; from pathlib import Path; time.sleep(2); Path(%r).write_text('escaped')" % str(marker)
    child = "import subprocess, sys, time; from pathlib import Path; subprocess.Popen([sys.executable, '-c', %r]); Path(%r).touch(); time.sleep(60)" % (grandchild, str(ready))
    parent = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', %r]); time.sleep(%s)" % (child, 0 if parent_exits else 60)
    with Process([sys.executable, "-c", parent]) as p:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists()
        if parent_exits:
            assert p.wait(timeout=10) == 0
        else:
            p.kill_tree()
    time.sleep(2.3)
    assert not marker.exists(), "a descendant outlived its owned process tree"


@pytest.mark.skipif(os.name != "nt", reason="Windows job startup failure")
def test_job_assignment_failure_never_runs_child(tmp_path, monkeypatch):
    from opc.core.windows import Job
    marker = tmp_path / "started"
    def refuse(self, process):
        raise OSError("assignment refused")
    monkeypatch.setattr(Job, "attach_and_resume", refuse)
    with pytest.raises(OSError, match="assignment refused"):
        Process([sys.executable, "-c", "from pathlib import Path; Path(%r).touch()" % str(marker)])
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows batch wrapper")
def test_batch_wrapper_is_rejected_without_execution(tmp_path):
    script = tmp_path / "unsafe.cmd"
    script.write_text("@echo off\nexit /b 0\n", encoding="utf-8")
    with pytest.raises(OSError, match="batch wrappers"):
        Process([str(script), "&", "echo", "unexpected"])


def test_writer_excludes_other_process_and_recovers_after_crash(tmp_path):
    lock = tmp_path / '.run.lock'
    script = '''
import os, sys, time
from opc.core.platform import lock_writer
fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
lock_writer(fd)
print('locked', flush=True)
time.sleep(60)
'''
    with subprocess.Popen([sys.executable, '-B', '-c', script, str(lock)],
                          stdout=subprocess.PIPE, text=True) as owner:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            assert owner.stdout.readline().strip() == 'locked'
            with pytest.raises(BlockingIOError):
                lock_writer(fd)
            owner.kill()
            owner.wait(timeout=10)
            lock_writer(fd)
            unlock_writer(fd)
        finally:
            os.close(fd)
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=10)


def test_exception_releases_project_lock(tmp_path):
    from opc.core.workspace import TopicWorkspace
    workspace = TopicWorkspace(tmp_path, 'research')
    workspace.initialize('Check evidence', 1)
    with pytest.raises(RuntimeError):
        with workspace.writer():
            raise RuntimeError('controller failed')
    with workspace.writer():
        pass
