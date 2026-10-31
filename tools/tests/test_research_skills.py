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
    for name in ('archa-map', 'archa-task', 'archa-loop'):
        assert (destination / name / 'SKILL.md').read_bytes() == (ROOT / 'skills' / name / 'SKILL.md').read_bytes()
    assert (skill / 'scripts/research.py').read_bytes() == (ROOT / 'skills/archa-map/scripts/research.py').read_bytes()
    moved = tmp_path / "relocated"
    shutil.move(str(skill), moved)
    target = tmp_path / "unrelated-project"
    target.mkdir()
    subprocess.run([sys.executable, str(moved / "scripts/initialize.py"),
                    "--project", str(target)], cwd=tmp_path, check=True, capture_output=True)
    created = subprocess.run([sys.executable, str(moved / 'scripts/research.py'), 'create',
                              '--project', str(target), '--name', 'relocated', '--title', 'Moved',
                              '--scope', 'offline check'], check=True, capture_output=True, text=True)
    assert Path(json.loads(created.stdout)['topic']).is_dir()
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
from opc.scaffold.onboard import onboard
from opc.core.model import OPCError, Cost
from opc.adapters.worker import WorkerCall
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
    return WorkerCall(role, True, Cost(0, 0, None), extra={'usage_complete': True}), json.dumps({'state': 'pending', 'reason': 'drafted; checks remain', 'evidence': []})
CodexWorker._run = fake_run
result = onboard(root, 'codex', brief)
assert result['preparation'] == 'pending', result
assert not list((root / '.opc/local/onboard').glob('**/task-brief.md'))
'''
    subprocess.run([sys.executable, "-B", "-c", script, str(project / ".opc/runtime"), str(project)],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    initialize.verify(project / ".opc/runtime")


def test_deployed_cli_records_unknown_usage_without_limits(tmp_path, runtime):
    project = tmp_path / 'metered-project'
    project.mkdir()
    initialize.initialize(project, runtime)
    cli = project / '.opc/archa.py'
    help_result = subprocess.run([sys.executable, str(cli), 'onboard', '--help'], capture_output=True, text=True)
    assert help_result.returncode == 0 and '--prior-wall-seconds' in help_result.stdout
    subprocess.run(['git', 'init', str(project)], check=True, capture_output=True)
    result = subprocess.run([sys.executable, str(cli), 'onboard', '-p', str(project), '--record-usage'], capture_output=True, text=True)
    assert result.returncode == 1 and json.loads(result.stdout)['preparation'] == 'pending'
    config = json.loads((project / '.opc/local/workers.json').read_text(encoding="utf-8"))
    assert config['budget'] == {'max_tokens': None, 'max_wall_seconds': 7200}
    assert (project / '.opc/project.json').exists()  # initialized without budget confirmation or model dispatch


def test_explicit_runtime_upgrade_keeps_budget_contract_and_backup(tmp_path, runtime):
    project = tmp_path / 'upgrade-project'
    project.mkdir()
    initialize.initialize(project, runtime)
    control = project / '.opc'
    (control / 'local').mkdir()
    (control / 'local/ledger.sqlite3').write_bytes(b'preserve cumulative accounting')
    (control / 'project.json').write_text('{"execution_enabled": false}', encoding="utf-8")
    previous = (control / 'runtime/manifest.json').read_bytes()
    changed = runtime / 'opc/__init__.py'
    changed.write_text(changed.read_text(encoding="utf-8") + '\n# updated package\n', encoding="utf-8")
    manifest = json.loads((runtime / 'manifest.json').read_text(encoding="utf-8"))
    manifest['files']['opc/__init__.py'] = initialize.digest(changed)
    manifest['snapshot_sha256'] = 'new-package-for-test'
    (runtime / 'manifest.json').write_text(json.dumps(manifest), encoding="utf-8")
    result = initialize.initialize(project, runtime, update=True)
    backup = Path(result['runtime_backup'])
    assert (backup / 'manifest.json').read_bytes() == previous
    assert (control / 'local/ledger.sqlite3').read_bytes() == b'preserve cumulative accounting'
    assert (control / 'project.json').read_text(encoding="utf-8") == '{"execution_enabled": false}'
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


spec_research = importlib.util.spec_from_file_location(
    'research_directories', ROOT / 'skills/archa-map/scripts/research.py')
research = importlib.util.module_from_spec(spec_research)
spec_research.loader.exec_module(research)


def write_topic_brief(project, directory):
    from opc.scaffold.brief import SECTIONS
    brief = directory / 'task-brief.md'
    fields = {
        'Source': f'Task: {(directory / "task.md").relative_to(project).as_posix()}\nStatus: ready-for-onboard',
        'Goal': 'Goal: explain baseline\nDone when: evidence recorded\nDirection: inspect baseline',
        'Scope and deliverables': '- D1: report\n- R1: evidence cited | verification=review\nObjective: none: explanation',
    }
    brief.write_text('\n\n'.join('## ' + name + '\n' + fields.get(name, 'Baseline evidence and scope recorded.')
                               for name in SECTIONS), encoding='utf-8')
    return brief


def test_topics_preserve_old_layout_runtime_and_same_session(tmp_path, runtime):
    root = tmp_path / 'project with spaces'
    root.mkdir()
    initialize.initialize(root, runtime)
    old = root / '.opc/research'
    old.mkdir()
    (old / 'tasks/r01-old').mkdir(parents=True)
    for rel in ('research-map.md', 'discussion.md', 'tasks/r01-old/task.md'):
        (old / rel).write_text('old evidence: ' + rel, encoding="utf-8")
    before = {p: p.read_bytes() for p in (root / '.opc').rglob('*') if p.is_file()}
    a = research.create(root, 'dma-scheduling', 'DMA', 'schedule')
    first = Path(a['topic'])
    first_files = {p: p.read_bytes() for p in first.rglob('*') if p.is_file()}
    b = research.create(root, 'dma-scheduling', 'DMA', 'other goal')
    assert Path(b['topic']).name == 'dma-scheduling-2'
    assert b['topic'] in b['task_directory'] and '"' in b['next']
    assert all(p.read_bytes() == content for p, content in (before | first_files).items())
    index = (old / 'index.md').read_text(encoding="utf-8")
    assert 'topics/dma-scheduling-2/research-map.md' in index and '(research-map.md)' in index
    # Fixed continuation: use the returned topic; no create on supplementary messages.
    with (first / 'discussion.md').open('a', encoding='utf-8') as stream:
        stream.write('\n补充：关注 DMA 排队。\n')
    assert len(list((old / 'topics').iterdir())) == 2
    initialize.initialize(root, runtime)
    assert all(p.read_bytes() == content for p, content in before.items())


def test_two_r01_real_onboard_resume_revision_and_history(tmp_path, runtime, monkeypatch):
    import re
    from opc.adapters.worker import WorkerCall
    from opc.core.model import Cost
    from opc.core.ledger import Ledger
    from opc.scaffold.onboard import onboard
    from opc.tests.conftest import component, task as contract_template
    root = tmp_path / 'two topics'
    root.mkdir()
    subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
    initialize.initialize(root, runtime)
    dirs = [Path(research.create(root, name, name, 'independent goal')['task_directory'])
            for name in ('dma', 'quantization')]
    briefs = [write_topic_brief(root, d) for d in dirs]
    targets = []
    revisions = {}
    def worker(self, role, prompt, tree, log, sandbox, schema):
        target = re.search(r'Target task ID: ([a-z0-9-]+)\.', prompt).group(1)
        targets.append(target)
        revision = revisions.get(target, 'r0001')
        path = root / f'.opc/tasks/{target}/revisions/{revision}/task.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(contract_template(task_id=target, revision=revision, component='main')), encoding="utf-8")
        (root / '.opc/components/main.json').write_text(json.dumps(component(component_id='main')), encoding="utf-8")
        log.mkdir(parents=True)
        (log / 'checks.txt').write_text('offline integration fixture', encoding="utf-8")
        return WorkerCall(role, True, Cost(0.01, 7, None), extra={'usage_complete': True}), json.dumps(
            dict(state='ready', evidence=[(log / 'checks.txt').relative_to(root).as_posix()]))
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', worker)
    ids = []
    for directory, brief in zip(dirs, briefs):
        selected = research.resolve(root, str(directory), prepare=True)
        task_id = selected['task_id']
        ids.append(task_id)
        assert research.resolve(root, str(directory), prepare=True)['task_id'] == task_id
        result = onboard(root, 'codex', brief=brief, task_id=task_id)
        assert result['ok'], result
        research.record(root, str(directory), task_id, 'r0001')
    assert len(set(ids)) == 2 and 't-main' not in ids and targets == ids
    old_contracts = {root / research.resolve(root, str(d))['contract']: (root / research.resolve(root, str(d))['contract']).read_bytes() for d in dirs}
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    initial_runs = {r['task_id']: r['run_id'] for r in ledger.runs()}
    for directory, brief, task_id in zip(dirs, briefs, ids):
        assert research.resolve(root, str(directory))['task_id'] == task_id
        assert onboard(root, 'codex', brief=brief, task_id=task_id)['ok']
        assert ledger.task_totals(task_id)['tokens'] == 7  # unchanged checks are reused
    # A recorded formal run freezes r0001. Revision preparation must preserve it.
    formal = ledger.create_run(task_id=ids[0], revision='r0001', task_digest='frozen',
                               component='main', base_commit='fixture', evaluator_digest='frozen',
                               toolchain_digest='fixture', champion_ref='', direction='offline history')
    ledger.set_run_state(formal, 'closed', 'offline historical fixture')
    initial_runs[ids[0]] = formal
    # Changed brief keeps its path-bound identity, but loop must return to preparation.
    briefs[0].write_text(briefs[0].read_text(encoding="utf-8") + '\nRevised evidence scope.\n', encoding="utf-8")
    with pytest.raises(ValueError, match='简报已变化'):
        research.resolve(root, str(dirs[0]))
    assert research.resolve(root, str(dirs[0]), True)['task_id'] == ids[0]
    revisions[ids[0]] = 'r0002'
    assert onboard(root, 'codex', brief=briefs[0], task_id=ids[0], revision='r0002')['ok']
    research.record(root, str(dirs[0]), ids[0], 'r0002', change='material', authorized=True)
    assert research.resolve(root, str(dirs[0]))['revision'] == 'r0002'
    assert research.resolve(root, str(dirs[1]))['revision'] == 'r0001'
    assert all(p.read_bytes() == content for p, content in old_contracts.items())
    assert {r['task_id']: r['run_id'] for r in ledger.runs()} == initial_runs
    assert ledger.task_totals(ids[0])['tokens'] == 14
    history = (root / '.opc/local/ledger.sqlite3').read_bytes()
    research.create(root, 'third', 'Third', 'new objective')
    initialize.initialize(root, runtime)
    assert (root / '.opc/local/ledger.sqlite3').read_bytes() == history


def test_legacy_external_collision_and_ambiguous_bindings(tmp_path):
    root = tmp_path
    (root / '.opc').mkdir()
    (root / '.opc/project.json').write_text('{}', encoding="utf-8")
    for rel in ('.opc/research/tasks/r01-old', 'specs/external-task'):
        directory = root / rel
        directory.mkdir(parents=True)
        (directory / 'task.md').write_text('Original source', encoding="utf-8")
        write_topic_brief(root, directory)
        task_id = 'old-task' if 'r01' in rel else 'external-task'
        contract = root / f'.opc/tasks/{task_id}/revisions/r0003/task.json'
        contract.parent.mkdir(parents=True)
        contract.write_text(json.dumps(dict(task_id=task_id, revision='r0003')), encoding="utf-8")
        decisions = root / '.opc/context/DECISIONS.md'
        decisions.parent.mkdir(exist_ok=True)
        with decisions.open('a', encoding='utf-8') as stream:
            stream.write(f'\nLegacy: {rel}/task-brief.md -> {task_id} r0003\n')
        with pytest.raises(ValueError, match='legacy handoff'):
            research.resolve(root, str(directory), True)
        research.record(root, str(directory), task_id, 'r0003')
        assert research.resolve(root, str(directory))['task_id'] == task_id
        assert contract.exists() and directory.exists()
    directory = Path(research.create(root, 'dma', 'DMA', 'goal')['task_directory'])
    write_topic_brief(root, directory)
    (root / '.opc/tasks/t-dma-r01-baseline').mkdir()
    row = research.resolve(root, str(directory), True)
    assert row['task_id'] == 't-dma-r01-baseline-2'
    conflicting = dict(row, task_id='different-task')
    research.append(decisions, conflicting)
    with pytest.raises(ValueError, match='ambiguous'):
        research.resolve(root, str(directory), True)


def test_directory_input_errors_are_read_only(tmp_path, monkeypatch):
    directory = Path(research.create(tmp_path, 'dma', 'DMA', 'goal')['task_directory'])
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    for bad in (None, str(tmp_path), str(directory.parents[1]), str(directory.parent), str(directory / 'task.md')):
        with pytest.raises(ValueError, match='任务目录'):
            research.resolve(tmp_path, bad, True)
    with pytest.raises(ValueError, match='archa-task'):
        research.resolve(tmp_path, str(directory))
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before
    write_topic_brief(tmp_path, directory)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match='尚未 onboard'):
        research.resolve(tmp_path, str(directory.relative_to(tmp_path)))


def test_explicit_parent_relative_task_directory(tmp_path, monkeypatch):
    directory = Path(research.create(tmp_path, 'relative', 'Relative', 'goal')['task_directory'])
    write_topic_brief(tmp_path, directory)
    cwd = tmp_path / 'working'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    with pytest.raises(ValueError, match='尚未 onboard'):
        research.resolve(tmp_path, '../' + directory.relative_to(tmp_path).as_posix())
