"""Crash at filesystem publication boundaries; restart the deployed CLI."""
import json
import subprocess
import sys

import pytest

from opc.tests.test_topic_cli import cli, project, scripted


def crash_step(project, boundary):
    code = '''
import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from opc.core.engine import TopicEngine
replace = os.replace
rename = pathlib.Path.rename
rmdir = pathlib.Path.rmdir
write = pathlib.Path.write_text
boundary = sys.argv[3]
def move(source, target):
    name = pathlib.Path(source).name
    if boundary == 'before-' + name: os._exit(73)
    result = replace(source, target)
    if boundary == 'after-' + name: os._exit(73)
    return result
def promote(source, target):
    if boundary == 'before-commit': os._exit(73)
    result = rename(source, target)
    if boundary == 'after-commit': os._exit(73)
    return result
def remove(path):
    if path.name == '.staging.commit' and boundary == 'before-cleanup': os._exit(73)
    return rmdir(path)
def prepare(path, *args, **kwargs):
    if path.parent.name == ".staging.expert" and boundary == "before-prepare": os._exit(73)
    result = write(path, *args, **kwargs)
    if path.parent.name == ".staging.expert" and boundary == "after-prepare":
        write(path, "# Half-written draft")
        os._exit(73)
    return result
pathlib.Path.write_text = prepare
os.replace = move
pathlib.Path.rename = promote
pathlib.Path.rmdir = remove
TopicEngine(sys.argv[2], 'research').step()
'''
    result = subprocess.run([sys.executable, '-c', code, str(project / '.archa/runtime'),
                             str(project), boundary], capture_output=True, text=True)
    assert result.returncode == 73, result.stderr


@pytest.mark.parametrize('boundary', ['after-commit', 'before-STATE.md', 'after-STATE.md',
                                      'before-probe.md', 'after-probe.md', 'before-cleanup'])
def test_restart_finishes_verified_expert_before_dispatch(project, boundary):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '3')
    scripted(project)
    crash_step(project, boundary)
    topic = project / '.archa/topics/research'
    assert cli(project, 'status')['publishing'] is True
    # Any repeated Expert would fail: only the committed probe may be executed.
    config = {'roles': {'expert': {
        'command': [sys.executable, '-c', 'raise RuntimeError("replayed")'],
        'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 5},
        'executor': {'preset': 'scripted'}}}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    state = cli(project, 'step')
    assert state['completed_rounds'] == 1
    assert state['next_action'] == 'expert'
    assert state['publishing'] is False
    assert 'Prepared one focused evidence question' in (topic / 'STATE.md').read_text()
    assert 'Observed the current probe' in (topic / 'steps/step-01/result.md').read_text()


@pytest.mark.parametrize('boundary', ['before-commit', 'before-prepare', 'after-prepare'])
def test_restart_discards_unverified_expert_and_keeps_logs_and_originals(project, boundary):
    cli(project, 'init', '--goal', 'Check evidence')
    scripted(project)
    topic = project / '.archa/topics/research'
    old_state = (topic / 'STATE.md').read_text()
    crash_step(project, boundary)
    step = topic / 'steps/step-01'
    (step / 'original.txt').write_text('raw observation')
    assert (topic / 'STATE.md').read_text() == old_state
    assert cli(project, 'status')['completed_rounds'] == 0
    assert cli(project, 'step')['next_action'] == 'executor'
    assert (step / 'original.txt').read_text() == 'raw observation'
    assert (step / '.expert.log').exists()
    assert not (step / '.staging.expert').exists()


@pytest.mark.parametrize('terminal', ['COMPLETED', 'BLOCKED'])
@pytest.mark.parametrize('boundary', ['after-commit', 'after-STATE.md', 'before-cleanup'])
def test_restart_recovers_terminal_state_without_probe_or_worker(project, terminal, boundary):
    cli(project, 'init', '--goal', 'Check evidence')
    command = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_text(p.read_text().replace('IN_PROGRESS', sys.argv[3])); pathlib.Path(sys.argv[2]).write_text('must not publish')"
    config = {'roles': {'expert': {'command': [sys.executable, '-c', command, '{state_file}', '{output_file}', terminal],
                                 'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 5},
                        'executor': {'preset': 'scripted'}}}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    crash_step(project, boundary)
    (project / '.archa/workers.json').write_text('{}')  # Recovery must not call a Worker.
    status = cli(project, 'step')
    assert status['status'] == terminal
    assert status['completed_rounds'] == 0
    assert status['next_action'] == terminal.lower()
    assert not (project / '.archa/topics/research/steps/step-01/probe.md').exists()


@pytest.mark.parametrize('boundary', ['before-.staging.result.md', 'after-.staging.result.md'])
def test_executor_restart_reuses_only_committed_result(project, boundary):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '3')
    scripted(project)
    cli(project, 'step')
    crash_step(project, boundary)
    completed = boundary.startswith('after')
    assert cli(project, 'status')['completed_rounds'] == int(completed)
    status = cli(project, 'step')
    assert status['completed_rounds'] == 1
    assert status['next_action'] == ('executor' if completed else 'expert')
    assert 'Observed the current probe' in (project / '.archa/topics/research/steps/step-01/result.md').read_text()


@pytest.mark.parametrize('terminal', ['COMPLETED', 'IN_PROGRESS', 'BLOCKED'])
def test_finalize_publication_recovers_without_an_experiment(project, terminal):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '1')
    scripted(project)
    cli(project, 'step')
    cli(project, 'step')
    code = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from opc.core.workspace import TopicWorkspace
w = TopicWorkspace(sys.argv[2], 'research')
with w.writer():
    directory = w.path / 'steps/step-02'
    directory.mkdir()
    stage = directory / '.staging.expert'
    stage.mkdir()
    (stage / 'STATE.md').write_text('# Exploration State\\nSTATUS: ' + sys.argv[3] + '\\nMAX_ROUNDS: 1\\n\\nFinal evidence digested.\\n')
    (stage / 'probe.md').write_text('must not publish')
    replace = os.replace
    def crash(source, target):
        result = replace(source, target)
        os._exit(73)
    os.replace = crash
    w.commit_expert(directory, 1, finalize=True)
'''
    result = subprocess.run([sys.executable, '-c', code, str(project / '.archa/runtime'),
                             str(project), terminal], capture_output=True, text=True)
    assert result.returncode == 73, result.stderr
    status = cli(project, 'step')
    assert status['status'] == ('COMPLETED' if terminal == 'COMPLETED' else 'BUDGET_EXHAUSTED')
    assert status['completed_rounds'] == 1
    topic = project / '.archa/topics/research'
    assert 'Final evidence digested.' in (topic / 'STATE.md').read_text()
    assert not (topic / 'steps/step-02/probe.md').exists()


@pytest.mark.parametrize(('mutation', 'error'), [
    ("text.replace('MAX_ROUNDS: 10', 'MAX_ROUNDS: 20')", 'cannot change MAX_ROUNDS'),
    ("text.replace('IN_PROGRESS', 'BUDGET_EXHAUSTED')", 'invalid normal-turn STATUS'),
    ("text", 'probe is missing or empty'),
])
def test_invalid_expert_draft_is_not_published_and_can_retry(project, mutation, error):
    cli(project, 'init', '--goal', 'Check evidence')
    state = project / '.archa/topics/research/STATE.md'
    old = state.read_bytes()
    command = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); text=p.read_text(); p.write_text(" + mutation + ")"
    config = {'roles': {'expert': {'command': [sys.executable, '-c', command, '{state_file}'],
                                 'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 5},
                        'executor': {'preset': 'scripted'}}}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    assert error in cli(project, 'step', ok=False)
    assert state.read_bytes() == old
    assert cli(project, 'status')['next_action'] == 'expert'
    scripted(project)
    assert cli(project, 'step')['next_action'] == 'executor'
