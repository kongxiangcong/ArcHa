"""Portable skill bundles and non-destructive project initialization."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "research_initialize", ROOT / "skills/archa-map/scripts/initialize.py")
initialize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(initialize)


@pytest.fixture
def runtime(tmp_path):
    runtime = tmp_path / "runtime"
    initialize.snapshot(ROOT, runtime)
    return runtime


def test_fresh_resume_and_preserve_contracts(tmp_path, runtime):
    project = tmp_path / "target with spaces"
    project.mkdir()
    first = initialize.initialize(project, runtime)
    assert first["execution_enabled"] is False
    assert {p.name for p in (project / ".opc").iterdir()} == {"runtime", "archa.py"}
    # Contract creation is a separate step; it must preserve the deployed runtime.
    subprocess.run([sys.executable, str(project / ".opc/archa.py"), "init", "-p", str(project),
                    "--project-id", "demo", "--name", "Demo", "--apply"],
                   check=True, capture_output=True)
    config_path = project / ".opc/project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["execution_enabled"] = True
    config_path.write_text(json.dumps(config), encoding="utf-8")
    original = config_path.read_bytes()
    second = initialize.initialize(project, runtime)
    assert second["existing_scaffold"] and second["execution_enabled"]
    assert config_path.read_bytes() == original
    proc = subprocess.run([sys.executable, str(project / ".opc/archa.py"), "--help"],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0 and "brief-check" in proc.stdout
    initialize.verify(project / ".opc/runtime")  # CLI did not create untracked bytecode.


def test_runtime_change_is_not_overwritten(tmp_path, runtime):
    project = tmp_path / "project"
    project.mkdir()
    initialize.initialize(project, runtime)
    changed = project / ".opc/runtime/opc/cli.py"
    changed.write_text("# locally changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="modified"):
        initialize.initialize(project, runtime)
    assert changed.read_text(encoding="utf-8") == "# locally changed\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL inheritance")
def test_runtime_inherits_project_acl_instead_of_private_temp_acl(tmp_path, runtime):
    project = tmp_path / "acl-project"
    project.mkdir()
    initialize.initialize(project, runtime)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "[System.IO.Directory]::GetAccessControl($env:ARCHA_TEST_RUNTIME).AreAccessRulesProtected"],
        env={**os.environ, "ARCHA_TEST_RUNTIME": str(project / ".opc/runtime")},
        capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False", "private staging ACL leaked into deployed runtime"


def test_existing_runtime_remains_pinned(tmp_path, runtime):
    project = tmp_path / "project"
    project.mkdir()
    initialize.initialize(project, runtime)
    original = (project / ".opc/runtime/manifest.json").read_bytes()
    changed = runtime / "opc/__init__.py"
    changed.write_text(changed.read_text(encoding="utf-8") + "\n# new packaged version\n", encoding="utf-8")
    manifest_path = runtime / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["opc/__init__.py"] = initialize.digest(changed)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    initialize.initialize(project, runtime)
    assert (project / ".opc/runtime/manifest.json").read_bytes() == original


def test_redirected_control_directory_is_rejected(tmp_path, runtime):
    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        (project / ".opc").symlink_to(elsewhere, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable; junctions tested separately")
        raise
    with pytest.raises(ValueError, match="redirected"):
        initialize.initialize(project, runtime)
    assert not list(elsewhere.iterdir())


def test_bundle_relocation_and_reinstall_backup(tmp_path):
    install = ROOT / "tools/install_research_skills.py"
    destination = tmp_path / "installed/skills"
    command = [sys.executable, str(install), "--destination", str(destination)]
    subprocess.run(command, check=True, capture_output=True)
    skill = destination / "archa-map"
    (skill / "local-note.txt").write_text("keep my local changes", encoding="utf-8")
    report = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
    backups = [Path(p) for p in report["backups"]]
    assert len(backups) == 3
    assert {Path(p).name for p in report["installed"]} == {
        "archa-map", "archa-task", "archa-loop"}
    assert (destination / "archa-loop/SKILL.md").is_file()
    assert (backups[0] / "local-note.txt").read_text(encoding="utf-8") == "keep my local changes"
    moved = tmp_path / "relocated"
    shutil.move(str(skill), moved)
    target = tmp_path / "unrelated-project"
    target.mkdir()
    subprocess.run([sys.executable, str(moved / "scripts/initialize.py"),
                    "--project", str(target)], cwd=tmp_path, check=True, capture_output=True)
    assert (target / ".opc/runtime/LICENSE").is_file()
    assert (target / ".opc/runtime/opc/scaffold/brief.py").is_file()
    initialize.verify(target / ".opc/runtime")


def test_runtime_allowlist_excludes_unrelated_files(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "opc", source / "opc")
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    shutil.copyfile(ROOT / "LICENSE", source / "LICENSE")
    (source / "opc/new_dev_tool.py").write_text("raise RuntimeError('not runtime')", encoding="utf-8")
    (source / "opc/notes.md").write_text("development notes", encoding="utf-8")
    target = tmp_path / "package"
    initialize.snapshot(source, target)
    manifest = initialize.verify(target)
    assert "opc/new_dev_tool.py" not in manifest["files"]
    assert "opc/README.md" not in manifest["files"]
    assert "pyproject.toml" not in manifest["files"]
    assert 'opc/core/results.py' in manifest['files']
    assert not any("tests" in Path(p).parts for p in manifest["files"])
    assert manifest["snapshot_sha256"] and manifest["source_commit"] is None


def test_snapshot_ignores_line_ending_only_differences(tmp_path):
    """A CRLF checkout must not be recorded as a source edit in the identity."""
    source = tmp_path / "source"
    shutil.copytree(ROOT / "opc", source / "opc")
    shutil.copyfile(ROOT / "LICENSE", source / "LICENSE")
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "config", "core.autocrlf", "true"],
                   check=True, capture_output=True)
    for rel in initialize.RUNTIME_FILES:
        path = source / rel
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@example",
                    "commit", "-qm", "base"], check=True, capture_output=True)

    initialize.snapshot(source, tmp_path / "clean")
    manifest = initialize.verify(tmp_path / "clean")
    assert manifest["source_commit"]
    assert manifest["differs_from_head"] == []

    edited = source / "opc/cli.py"
    edited.write_bytes(edited.read_bytes() + b"\n# changed\n")
    initialize.snapshot(source, tmp_path / "edited")
    assert initialize.verify(tmp_path / "edited")["differs_from_head"] == ["opc/cli.py"]


def test_deployed_runtime_brief_to_onboard(tmp_path, runtime):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
    initialize.initialize(project, runtime)
    script = r'''
import json
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, sys.argv[1])
from opc.scaffold.brief import SECTIONS
from opc.scaffold.onboard import _draft as onboard
from opc.core.model import OPCError
from opc.adapters.codex import CodexWorker
import opc.core.engine, opc.core.promote, opc.adapters.dsh, opc.adapters.scripted
root = Path(sys.argv[2])
research = root / '.opc/research'
research.mkdir()
(research / 'research-map.md').write_text('# Map\n')
brief = research / 'task-brief.md'
fields = {
    'Source': 'Map: .opc/research/research-map.md\nStatus: draft',
    'Goal': 'Goal: explain input reuse\nDone when: every stage cited\nDirection: undecided',
    'Scope and deliverables': '- D1: mechanism note\n'
                              '- R1: every claim cited | verification=review\n'
                              'Objective: none: no numeric metric',
}
body = '\n\n'.join('## ' + section + '\n' + fields.get(
    section, 'Current scope agreed; budget remains unknown until onboarding.')
    for section in SECTIONS)
brief.write_text(body)
try:
    onboard(root, 'codex', brief)
except OPCError:
    pass
else:
    raise AssertionError('draft was accepted')
assert not (root / '.opc/project.json').exists()
brief.write_text(body.replace('Status: draft', 'Status: ready-for-onboard'))
def fake_run(self, role, prompt, tree, log, sandbox, schema):
    config = json.loads((root / '.opc/project.json').read_text())
    assert config['execution_enabled'] is False
    assert (root / '.opc/tasks/t-main/revisions/r0001/task.json').is_file()
    assert brief.read_text() in prompt
    return SimpleNamespace(ok=True, call_id='fake', cost=SimpleNamespace(tokens=0), error=''), 'mock draft'
CodexWorker._run = fake_run
result = onboard(root, 'codex', brief)
assert result['ok'], result
assert (root / '.opc/local/onboard/task-brief.md').read_text() == brief.read_text()
'''
    subprocess.run([sys.executable, "-B", "-c", script, str(project / ".opc/runtime"), str(project)],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    initialize.verify(project / ".opc/runtime")


def test_deployed_cli_refuses_unmetered_preparation(tmp_path, runtime):
    project = tmp_path / 'metered-project'
    project.mkdir()
    initialize.initialize(project, runtime)
    cli = project / '.opc/archa.py'
    help_result = subprocess.run([sys.executable, str(cli), 'onboard', '--help'], capture_output=True, text=True)
    assert help_result.returncode == 0 and '--prior-wall-seconds' in help_result.stdout
    result = subprocess.run([sys.executable, str(cli), 'onboard', '-p', str(project)], capture_output=True, text=True)
    assert result.returncode != 0 and 'accounting_unknown' in result.stdout
    assert not (project / '.opc/project.json').exists()  # no drafting/model dispatch


def test_explicit_runtime_upgrade_keeps_budget_contract_and_backup(tmp_path, runtime):
    project = tmp_path / 'upgrade-project'
    project.mkdir()
    initialize.initialize(project, runtime)
    control = project / '.opc'
    (control / 'local').mkdir()
    (control / 'local/ledger.sqlite3').write_bytes(b'preserve cumulative accounting')
    (control / 'project.json').write_text('{"execution_enabled": false}')
    previous = (control / 'runtime/manifest.json').read_bytes()
    changed = runtime / 'opc/__init__.py'
    changed.write_text(changed.read_text() + '\n# updated package\n')
    manifest = json.loads((runtime / 'manifest.json').read_text())
    manifest['files']['opc/__init__.py'] = initialize.digest(changed)
    manifest['snapshot_sha256'] = 'new-package-for-test'
    (runtime / 'manifest.json').write_text(json.dumps(manifest))
    result = initialize.initialize(project, runtime, update=True)
    backup = Path(result['runtime_backup'])
    assert (backup / 'manifest.json').read_bytes() == previous
    assert (control / 'local/ledger.sqlite3').read_bytes() == b'preserve cumulative accounting'
    assert (control / 'project.json').read_text() == '{"execution_enabled": false}'
    initialize.verify(control / 'runtime')
    cli = subprocess.run([sys.executable, str(control / 'archa.py'), 'results', '--help'],
                         capture_output=True, text=True)
    assert cli.returncode == 0 and '--sync-run' in cli.stdout
    assert initialize.initialize(project, runtime, update=True)['runtime_backup'] is None


def test_runtime_upgrade_refuses_active_controller(tmp_path, runtime):
    from opc.core.ledger import Ledger
    project = tmp_path / 'active-project'
    project.mkdir()
    initialize.initialize(project, runtime)
    ledger = Ledger(project / '.opc/local/ledger.sqlite3')
    before = (project / '.opc/runtime/manifest.json').read_bytes()
    with ledger.writer():
        with pytest.raises(ValueError, match='active controller'):
            initialize.upgrade_runtime(project / '.opc', runtime)
    assert (project / '.opc/runtime/manifest.json').read_bytes() == before
