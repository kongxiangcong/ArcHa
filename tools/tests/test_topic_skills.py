"""Installed skills use only the independently deployed topic runtime."""
from opc.tests.worker_fixture import custom
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def call(*args, code=0, cwd=None):
    result = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == code, (result.stdout, result.stderr)
    return json.loads(result.stdout)


def test_installed_skills_deploy_init_run_and_report(tmp_path):
    skills = tmp_path / 'skills'
    call(ROOT / 'tools/install_research_skills.py', '--destination', skills)
    project = tmp_path / 'project'
    project.mkdir()
    old = project / '.opc/history.txt'
    old.parent.mkdir()
    old.write_text('preserved legacy evidence')
    call(skills / 'archa-discuss/scripts/initialize.py', '--project', project)
    entry = project / '.archa/archa.py'
    call(entry, 'init', '-p', project, '--topic', 'evidence', '--goal', 'Explain observations', '--max-rounds', 1)
    (project / '.archa/workers.json').write_text(json.dumps({r: custom() for r in ('expert', 'executor')}))
    args = ['-p', project, '--topic', 'evidence']
    result = call(entry, 'run', *args, code=5, cwd=tmp_path)
    assert result['completed_rounds'] == 1
    topic = project / '.archa/topics/evidence'
    assert not (topic / 'PROGRESS_LOG.md').exists()
    before = {p: p.read_bytes() for p in topic.rglob('*') if p.is_file()}
    report = call(entry, 'report', *args, cwd=tmp_path)
    body = Path(report['report']).read_text()
    assert 'BUDGET_EXHAUSTED' in body and 'Observed the current probe' in body
    assert 'steps/step-01/result.md' in body and 'STATE.md' in body
    assert all(p.read_bytes() == data for p, data in before.items())
    assert call(entry, 'status', *args)['completed_rounds'] == 1
    assert old.read_text() == 'preserved legacy evidence'


def test_deployed_worker_check_is_read_only(tmp_path):
    project = tmp_path
    call(ROOT / 'skills/archa-discuss/scripts/initialize.py', '--project', project)
    entry = project / '.archa/archa.py'
    args = ['-p', project, '--topic', 'check']
    call(entry, 'init', *args, '--goal', 'inspect')
    before = {p: p.read_bytes() for p in project.rglob('*') if p.is_file()}
    assert call(entry, 'check', *args)['roles'] == ['expert', 'executor']
    assert all(p.read_bytes() == body for p, body in before.items())


def test_installed_stop_resume_preserves_pending_probe_and_reports_offline(tmp_path):
    import time
    skills = tmp_path / 'skills'
    call(ROOT / 'tools/install_research_skills.py', '--destination', skills)
    project = tmp_path / 'target'
    project.mkdir()
    call(skills / 'archa-discuss/scripts/initialize.py', '--project', project)
    entry = project / '.archa/archa.py'
    args = ['-p', project, '--topic', 'intervene']
    call(entry, 'init', *args, '--goal', 'Check evidence', '--max-rounds', 1)
    config = project / '.archa/workers.json'
    roles = {r: custom() for r in ('expert', 'executor')}
    config.write_text(json.dumps(roles))
    call(entry, 'step', *args)
    roles['executor'] = {'provider': 'custom', 'command': [sys.executable, '-c', "import pathlib,time; pathlib.Path('started').touch(); print('visible progress',flush=True); time.sleep(30)"],
                         'timeout_seconds': 40}
    config.write_text(json.dumps(roles))
    running = subprocess.Popen([sys.executable, str(entry), 'run', *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 8
        while not (project / 'started').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (project / 'started').exists()
        assert call(entry, 'stop', *args)['activity'] == 'idle'
        running.communicate(timeout=5)
        topic = project / '.archa/topics/intervene'
        probe = topic / 'steps/step-01/probe.md'
        assert 'visible progress' in probe.with_name('.executor.log').read_text()
        original_probe = probe.read_bytes()
        roles['executor'] = custom()
        config.write_text(json.dumps(roles))
        assert call(entry, 'resume', *args, code=5)['completed_rounds'] == 1
        assert probe.read_bytes() == original_probe
        assert original_probe.decode() in probe.with_name('result.md').read_text()
        before = {p: p.read_bytes() for p in topic.rglob('*') if p.is_file()}
        report = call(entry, 'report', *args)
        assert 'Check evidence' in Path(report['report']).read_text()
        assert all(p.read_bytes() == body for p, body in before.items())
    finally:
        if running.poll() is None:
            call(entry, 'stop', *args)
            running.communicate(timeout=5)


def test_deployed_explicit_correction_reissues_probe_preserving_evidence_and_budget(tmp_path):
    call(ROOT / 'skills/archa-discuss/scripts/initialize.py', '--project', tmp_path)
    entry = tmp_path / '.archa/archa.py'
    args = ['-p', tmp_path, '--topic', 'correct']
    call(entry, 'init', *args, '--goal', 'Investigate input order', '--max-rounds', 2)
    config = tmp_path / '.archa/workers.json'
    config.write_text(json.dumps({r: custom() for r in ('expert', 'executor')}))
    call(entry, 'step', *args)
    call(entry, 'step', *args)
    call(entry, 'step', *args)
    topic = tmp_path / '.archa/topics/correct'
    completed = {p: p.read_bytes() for p in (topic / 'steps/step-01').iterdir() if p.is_file()}
    pending = topic / 'steps/step-02/probe.md'
    original = pending.read_bytes()
    stopped = call(entry, 'stop', *args)
    assert stopped['activity'] == 'idle' and not stopped['publishing']
    goal = topic / 'GOAL.md'
    goal.write_text(goal.read_text().replace('Investigate input order', 'Investigate cancellation at 2**53'))
    # Editing the goal alone leaves the already-published probe in place.
    assert call(entry, 'status', *args)['next_action'] == 'executor'
    assert pending.read_bytes() == original
    pending.unlink()
    assert call(entry, 'status', *args)['next_action'] == 'expert'
    resumed = call(entry, 'resume', *args, code=5)
    assert resumed['completed_rounds'] == 2 and resumed['max_rounds'] == 2
    assert 'Investigate cancellation at 2**53' in pending.read_text()
    assert 'Investigate input order' not in pending.read_text()
    assert pending.read_text() in pending.with_name('result.md').read_text()
    assert all(p.read_bytes() == data for p, data in completed.items())
    # Neither read-only status nor report can invoke these now-invalid Workers.
    config.write_text('{}')
    authoritative = {p: p.read_bytes() for p in topic.rglob('*') if p.is_file()}
    assert call(entry, 'status', *args)['status'] == 'BUDGET_EXHAUSTED'
    assert not (topic / 'PROGRESS_LOG.md').exists()
    report = call(entry, 'report', *args)
    assert 'Investigate cancellation at 2**53' in Path(report['report']).read_text()
    assert all(p.read_bytes() == data for p, data in authoritative.items())
    assert {p for p in topic.rglob('*') if p.is_file()} - authoritative.keys() == {Path(report['report'])}


def test_runtime_upgrade_preserves_legacy_config_then_manual_migration_runs(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    initializer = ROOT / 'skills/archa-discuss/scripts/initialize.py'
    call(initializer, '--project', project)
    entry = project / '.archa/archa.py'
    args = ['-p', project, '--topic', 'migration']
    call(entry, 'init', *args, '--goal', 'Check preserved evidence', '--max-rounds', 1)
    config = project / '.archa/workers.json'
    config.write_text('{"roles":{"expert":{"preset":"codex"},"executor":{"preset":"codex"}}}')
    topic = project / '.archa/topics/migration'
    before = {p: p.read_bytes() for p in [config, topic / 'GOAL.md', topic / 'STATE.md']}
    call(initializer, '--project', project, '--update')
    assert all(p.read_bytes() == body for p, body in before.items())
    rejected = subprocess.run([sys.executable, str(entry), 'check', *map(str, args)], capture_output=True, text=True)
    assert rejected.returncode == 2 and 'manual migration' in rejected.stderr
    config.write_text(json.dumps({role: custom() for role in ('expert', 'executor')}))
    assert call(entry, 'run', *args, code=5)['completed_rounds'] == 1
    assert 'Check preserved evidence' in (topic / 'steps/step-01/result.md').read_text()
