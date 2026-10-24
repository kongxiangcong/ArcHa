"""Real OS probes: never mock away the lock or the spawned process tree."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from opc.core.platform import Process


def test_cli_engine_imports():
    subprocess.run([sys.executable, "-B", "-c", "from opc.core.engine import Engine"], check=True)


def test_writer_excludes_other_process_and_recovers_after_crash(tmp_path):
    from opc.core.ledger import Ledger
    db = tmp_path / "ledger.sqlite3"
    script = """
import sys, time
from pathlib import Path
from opc.core.ledger import Ledger
with Ledger(Path(sys.argv[1])).writer():
    print('locked', flush=True)
    time.sleep(60)
"""
    with subprocess.Popen([sys.executable, "-B", "-c", script, str(db)],
                          stdout=subprocess.PIPE, text=True) as owner:
        try:
            assert owner.stdout.readline().strip() == "locked"
            ledger = Ledger(db)
            try:
                from opc.core.model import OPCError
                with pytest.raises(OPCError, match="another controller"):
                    with ledger.writer():
                        pytest.fail("two writers acquired the lock")
                owner.kill()
                owner.wait(timeout=10)
                with ledger.writer():
                    pass
            finally:
                ledger.db.close()
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=10)


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


def test_gate_timeout_returns_infra_signal(tmp_path):
    from opc.domains.command import run_command
    code, _, _, timed_out = run_command(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        tmp_path, dict(os.environ), .2, tmp_path / "logs")
    assert code is None and timed_out


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


@pytest.mark.parametrize("path", [".OPC/project.json", "Tests/check.py", "../params.json",
                                  "C:/params.json", "params.json:stream", "a/../params.json",
                                  "a\\params.json", "params.json."])
def test_path_denials_are_portable(make_project, path):
    from opc.tests.conftest import component
    from opc.core.config import ComponentConfig
    root = make_project(comp=component(editable=["**"], frozen=["tests/**"], scratch=["**"]))
    comp = ComponentConfig.load(root, "toy")
    assert not comp.is_editable(path)
    assert not comp.is_scratch(path)


def test_toolchain_identity_includes_platform(make_project, monkeypatch):
    from opc.core.config import ComponentConfig
    from opc.domains.command import CommandDomain
    domain = CommandDomain(ComponentConfig.load(make_project(), "toy"))
    before, details = domain.toolchain()
    assert "unavailable" not in details["{python} --version"]
    monkeypatch.setattr("opc.domains.command.platform.system", lambda: "AnotherOS")
    assert domain.toolchain()[0] != before


@pytest.mark.parametrize("newline", [b"", b"\n", b"\r\n"])
def test_git_patch_preserves_bytes_and_unicode_paths(make_project, tmp_path, newline):
    from opc.core.workspace import git, extract_patch, apply_patch, Workspaces
    root = make_project()
    name = "space 中文.txt"
    original = b"before" + newline
    changed = b"after" + newline
    git("config", "core.autocrlf", "false", cwd=root)
    (root / name).write_bytes(original)
    git("add", "-A", cwd=root)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "unicode", cwd=root)
    base = git("rev-parse", "HEAD", cwd=root).strip()
    (root / name).write_bytes(changed)
    git("add", "-A", cwd=root)
    patch = extract_patch(root, base, [name])
    ws = Workspaces(root, tmp_path / "trees")
    tree = ws.checkout("eval", base)
    try:
        apply_patch(tree, patch)
        assert (tree / name).read_bytes() == changed
    finally:
        ws.drop_all()


@pytest.mark.parametrize("worker", ["codex", "dsh"])
def test_worker_timeout_is_infrastructure(worker, tmp_path):
    from opc.adapters.codex import CodexWorker
    from opc.adapters.dsh import DshWorker
    script = tmp_path / "worker with spaces.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")
    cls = CodexWorker if worker == "codex" else DshWorker
    call, _ = cls({"binary": [sys.executable, str(script)], "timeout_s": .2})._run(
        "expert", "test", tmp_path, tmp_path / "logs", "read-only", None)
    assert not call.ok and call.extra["infra"]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_junction_is_not_an_editable_directory(make_project, tmp_path):
    from opc.core.workspace import sandbox
    from opc.core.config import ComponentConfig
    from opc.tests.conftest import component
    root = make_project(comp=component(editable=["redirect/**"]))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_text("external", encoding="utf-8")
    link = root / "redirect"
    subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
                   check=True, capture_output=True)
    try:
        report = sandbox(ComponentConfig.load(root, "toy"), root, "HEAD")
        assert not report.ok and "redirect/payload.txt" in report.violations
    finally:
        link.rmdir()  # unlink the junction only; never recurse into its target
    assert (outside / "payload.txt").read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(os.name != "nt", reason="Windows batch wrapper")
def test_batch_wrapper_is_rejected_without_execution(tmp_path):
    script = tmp_path / "unsafe.cmd"
    script.write_text("@echo off\nexit /b 0\n", encoding="utf-8")
    with pytest.raises(OSError, match="batch wrappers"):
        Process([str(script), "&", "echo", "unexpected"])


def test_exception_releases_writer_lock(tmp_path):
    from opc.core.ledger import Ledger
    ledger = Ledger(tmp_path / "db")
    try:
        with pytest.raises(RuntimeError):
            with ledger.writer():
                raise RuntimeError("controller failed")
        with ledger.writer():
            pass
    finally:
        ledger.db.close()


@pytest.mark.parametrize("argv", [["cmd.exe", "/c", "echo bypass"],
                                  ["powershell.exe", "-Command", "echo bypass"],
                                  ["pwsh", "-enc", "ignored"]])
def test_inline_windows_shell_gate_rejected(make_project, argv):
    from opc.tests.conftest import component
    from opc.core.config import ComponentConfig
    from opc.core.model import OPCError
    root = make_project(comp=component(gates=[{"id": "unsafe", "argv": argv, "metrics": "m.json"}]))
    with pytest.raises(OPCError, match="inline shell"):
        ComponentConfig.load(root, "toy")
