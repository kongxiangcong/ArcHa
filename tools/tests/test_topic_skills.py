"""Installed skills use only the independently deployed topic runtime."""
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
    (project / '.archa/workers.json').write_text(json.dumps({'roles': {r: {'preset': 'scripted'} for r in ('expert', 'executor')}}))
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


def test_installed_stop_edit_resume_report(tmp_path):
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
    roles = {r: {'preset': 'scripted'} for r in ('expert', 'executor')}
    config.write_text(json.dumps({'roles': roles}))
    call(entry, 'step', *args)
    roles['executor'] = {'command': [sys.executable, '-c', "import pathlib,time; pathlib.Path('started').touch(); print('visible progress',flush=True); time.sleep(30)"],
                         'input_mode': 'stdin', 'output_mode': 'stdout', 'timeout_seconds': 40}
    config.write_text(json.dumps({'roles': roles}))
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
        probe.write_text('Human corrected question')
        roles['executor'] = {'preset': 'scripted'}
        config.write_text(json.dumps({'roles': roles}))
        assert call(entry, 'resume', *args, code=5)['completed_rounds'] == 1
        assert 'Human corrected question' in probe.with_name('result.md').read_text()
        before = {p: p.read_bytes() for p in topic.rglob('*') if p.is_file()}
        report = call(entry, 'report', *args)
        assert 'Human corrected question' in Path(report['report']).read_text()
        assert all(p.read_bytes() == body for p, body in before.items())
    finally:
        if running.poll() is None:
            call(entry, 'stop', *args)
            running.communicate(timeout=5)
