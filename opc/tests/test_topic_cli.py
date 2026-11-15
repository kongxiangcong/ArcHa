"""Topic behavior through the independently deployed project-local CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path):
    target = tmp_path / 'project'
    target.mkdir()
    result = subprocess.run([sys.executable, str(ROOT / 'skills/archa-map/scripts/initialize.py'),
                             '--project', str(target), '--topic-runtime'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return target


def cli(project, *args, ok=True):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), *args,
                             '-p', str(project), *([] if '--topic' in args else ['--topic', 'research'])],
                            cwd=project, env=env, capture_output=True, text=True)
    if ok:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert result.returncode != 0
    return result.stderr


def scripted(project):
    config = {'roles': {role: {'preset': 'scripted'} for role in ('expert', 'executor')}}
    (project / '.archa/workers.json').write_text(json.dumps(config))


def test_deployed_topic_handoff(project):
    initial = cli(project, 'init', '--goal', 'Check the supplied evidence', '--max-rounds', '3')
    assert initial['next_action'] == 'expert'
    scripted(project)
    first = cli(project, 'step')
    assert first['next_action'] == 'executor'
    assert first['completed_rounds'] == 0
    topic = project / '.archa/topics/research'
    assert 'Check the supplied evidence' in (topic / 'steps/step-01/probe.md').read_text()
    second = cli(project, 'step')
    assert second['next_action'] == 'expert'
    assert second['completed_rounds'] == 1
    assert 'Observed the current probe' in (topic / 'steps/step-01/result.md').read_text()
    assert cli(project, 'status') == second


def test_initialization_preserves_material_and_rejects_empty_goal(project):
    cli(project, 'init')
    assert 'GOAL.md is empty' in cli(project, 'step', ok=False)
    topic = project / '.archa/topics/research'
    goal = topic / 'GOAL.md'
    assert 'Environment entry' in goal.read_text()
    assert 'Completion criteria' in goal.read_text()
    goal.write_text('A user supplied goal')
    scripted(project)
    before = {p: p.read_bytes() for p in (goal, topic / 'STATE.md', project / '.archa/workers.json')}
    cli(project, 'init', '--goal', 'replacement', '--max-rounds', '99')
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize(('header', 'error'), [
    ('STATUS: IN_PROGRESS\n', 'missing MAX_ROUNDS'),
    ('MAX_ROUNDS: 3\n', 'missing STATUS'),
    ('STATUS: IN_PROGRESS\nSTATUS: COMPLETED\nMAX_ROUNDS: 3\n', 'duplicate STATUS'),
    ('STATUS: IN_PROGRESS\nMAX_ROUNDS: 3\nMAX_ROUNDS: 4\n', 'duplicate MAX_ROUNDS'),
    ('STATUS: UNKNOWN\nMAX_ROUNDS: 3\n', 'invalid STATUS'),
    ('STATUS: IN_PROGRESS\nMAX_ROUNDS: 0\n', 'positive integer'),
    ('STATUS: IN_PROGRESS\nMAX_ROUNDS: 1.5\n', 'positive integer'),
])
def test_invalid_metadata_is_reported_without_modification(project, header, error):
    cli(project, 'init', '--goal', 'Check evidence')
    state = project / '.archa/topics/research/STATE.md'
    state.write_text('# Exploration State\n' + header + '\nBody\n')
    before = state.read_bytes()
    assert error in cli(project, 'status', ok=False)
    assert state.read_bytes() == before


def test_status_is_read_only_and_round_names_are_strict(project):
    cli(project, 'init', '--goal', 'Check evidence')
    steps = project / '.archa/topics/research/steps'
    log_only = steps / 'step-01'
    log_only.mkdir()
    (log_only / '.expert.log').write_text('interrupted')
    assert cli(project, 'status')['completed_rounds'] == 0
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in project.rglob('*') if p.is_file()}
    cli(project, 'status')
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before
    (steps / 'step-1').mkdir()
    assert 'noncanonical round' in cli(project, 'status', ok=False)


def test_legacy_records_are_preserved_but_not_executed(project):
    legacy = project / '.opc/local/runs/old'
    legacy.mkdir(parents=True)
    (legacy / 'record.md').write_text('historical observation')
    assert 'STATE.md' in cli(project, 'step', ok=False)
    assert (legacy / 'record.md').read_text() == 'historical observation'


def test_cross_topic_writes_share_stable_project_lock(project):
    cli(project, 'init', '--goal', 'Check evidence')
    # Another real process owns the same OS lock; queries remain available.
    code = '''
import os, sys
sys.path.insert(0, sys.argv[1])
from opc.core.platform import lock_writer
fd = os.open(sys.argv[2], os.O_RDWR)
lock_writer(fd)
print('locked', flush=True)
sys.stdin.read()
'''
    with subprocess.Popen([sys.executable, '-c', code, str(project / '.archa/runtime'),
                           str(project / '.archa/.run.lock')], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as owner:
        try:
            assert owner.stdout.readline().strip() == 'locked'
            assert 'lock is held' in cli(project, 'step', ok=False)
            assert 'lock is held' in cli(project, 'init', '--topic', 'other', ok=False)
            assert cli(project, 'status')['completed_rounds'] == 0
        finally:
            owner.stdin.close()
            owner.wait(timeout=10)
    scripted(project)
    assert cli(project, 'step')['next_action'] == 'executor'


def test_topic_launcher_cannot_dispatch_legacy_commands(project):
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), 'onboard',
                             '-p', str(project)], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'invalid choice' in result.stderr
