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
                             '--project', str(target)], capture_output=True, text=True)
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


def test_commands_accept_prompt_files_and_stdout_results(project):
    cli(project, 'init', '--goal', 'Investigate evidence')
    script = project / 'worker.py'
    script.write_text("""import pathlib, sys
role, state, output, prompt = sys.argv[1:]
assert 'Investigate evidence' in pathlib.Path(prompt).read_text()
if role == 'expert':
    assert 'STATUS: IN_PROGRESS' in pathlib.Path(state).read_text()
    pathlib.Path(state).write_text(pathlib.Path(state).read_text() + '\\nEvidence reviewed.\\n')
    pathlib.Path(output).write_text('One focused question')
else:
    print('Actual observation')
    print('Diagnostic only', file=sys.stderr)
""")
    config = {'roles': {role: {'command': [sys.executable, str(script), role,
                '{state_file}', '{output_file}', '{prompt_file}'], 'input_mode': 'file',
                'output_mode': 'file' if role == 'expert' else 'stdout', 'timeout_seconds': 5}
                for role in ('expert', 'executor')}}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    assert cli(project, 'step')['next_action'] == 'executor'
    assert cli(project, 'step')['completed_rounds'] == 1
    step = project / '.archa/topics/research/steps/step-01'
    assert (step / 'result.md').read_text() == 'Actual observation\n'
    assert 'Diagnostic only' in (step / '.executor.log').read_text()


@pytest.mark.parametrize(('change', 'message'), [
    ({'preset': 'unknown'}, 'unknown preset'),
    ({'command': []}, 'nonempty string argv'),
    ({'legacy': 'codex'}, 'unknown fields'),
    ({'input_mode': 'invalid'}, 'input_mode'),
    ({'output_mode': 'stdout'}, 'output_mode'),
    ({'timeout_seconds': 0}, 'timeout_seconds'),
    ({'timeout_seconds': True}, 'timeout_seconds'),
    ({'env': []}, 'env'),
    ({'command': ['{model}']}, 'unavailable template variable'),
    ({'command': ['{unknown}']}, 'unavailable template variable'),
])
def test_invalid_worker_configuration_fails_before_dispatch(project, change, message):
    cli(project, 'init', '--goal', 'Check evidence')
    spec = {'command': [sys.executable, '-c', 'raise Exception("must not run")'],
            'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 5}
    if 'preset' in change:
        spec.pop('command')
    spec.update(change)
    (project / '.archa/workers.json').write_text(json.dumps({'roles': {
        'expert': spec, 'executor': {'preset': 'scripted'}}}))
    assert message in cli(project, 'step', ok=False)
    assert cli(project, 'status')['next_action'] == 'expert'


@pytest.mark.parametrize(('body', 'message'), [
    ("pathlib.Path(sys.argv[1]).write_text('partial'); sys.exit(7)", 'code 7'),
    ("pathlib.Path(sys.argv[1]).write_text('   ')", 'blank'),
    ("print('stdout is not a fallback')", 'missing'),
    ("print('before timeout', flush=True); time.sleep(10)", 'timed out'),
])
def test_executor_failures_preserve_logs_without_publishing(project, body, message):
    cli(project, 'init', '--goal', 'Check evidence')
    scripted(project)
    cli(project, 'step')
    spec = {'command': [sys.executable, '-c', 'import pathlib, sys, time; ' + body, '{output_file}'],
            'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': .2}
    (project / '.archa/workers.json').write_text(json.dumps({'roles': {
        'expert': {'preset': 'scripted'}, 'executor': spec}}))
    assert message in cli(project, 'step', ok=False)
    status = cli(project, 'status')
    assert status['next_action'] == 'executor'
    assert status['completed_rounds'] == 0
    step = project / '.archa/topics/research/steps/step-01'
    assert not (step / 'result.md').exists()
    if message == 'timed out':
        assert 'before timeout' in (step / '.executor.log').read_text()


def test_retry_cannot_publish_previous_failed_result(project):
    cli(project, 'init', '--goal', 'Check evidence')
    scripted(project)
    cli(project, 'step')
    config = {'roles': {'expert': {'preset': 'scripted'}, 'executor': {
        'command': [sys.executable, '-c', "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('failed output'); sys.exit(1)", '{output_file}'],
        'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 5}}}
    path = project / '.archa/workers.json'
    path.write_text(json.dumps(config))
    cli(project, 'step', ok=False)
    config['roles']['executor']['command'] = [sys.executable, '-c', 'pass']
    path.write_text(json.dumps(config))
    assert 'missing' in cli(project, 'step', ok=False)


@pytest.mark.parametrize('parent_exits', [False, True])
def test_streamed_logs_and_descendants_finish_before_result_publish(project, parent_exits):
    import time
    cli(project, 'init', '--goal', 'Check evidence')
    scripted(project)
    cli(project, 'step')
    marker = project / 'descendant-wrote'
    child = f"import time; from pathlib import Path; time.sleep(1.5); Path({str(marker)!r}).touch()"
    script = project / 'process.py'
    script.write_text("import pathlib,subprocess,sys,time\n"
                      "assert 'Check evidence' in sys.stdin.read()\n"
                      f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                      "print('visible while running', flush=True)\n"
                      "print('diagnostic', file=sys.stderr, flush=True)\n"
                      "pathlib.Path(sys.argv[1]).write_text('Observation')\n"
                      f"time.sleep({.5 if parent_exits else 10})\n")
    config = {'roles': {'expert': {'preset': 'scripted'}, 'executor': {
        'command': [sys.executable, str(script), '{output_file}'],
        'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 1}}}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    process = subprocess.Popen([sys.executable, str(project / '.archa/archa.py'), 'step',
                                '-p', str(project), '--topic', 'research'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    step = project / '.archa/topics/research/steps/step-01'
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            log = step / '.executor.log'
            if log.exists() and 'visible while running' in log.read_text():
                break
            time.sleep(.01)
        assert process.poll() is None
        assert 'visible while running' in log.read_text()
        stdout, stderr = process.communicate(timeout=10)
        assert (process.returncode == 0) == parent_exits, stderr
        time.sleep(1.6)
        assert not marker.exists()
        assert (step / 'result.md').exists() == parent_exits
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture; Windows native argv tested separately")
def test_missing_project_config_uses_distributed_codex_preset(project):
    cli(project, 'init', '--goal', 'Check evidence')
    scripted(project)
    cli(project, 'step')
    (project / '.archa/workers.json').unlink()
    # Exercise the deployed default through a real executable, without model access.
    binary = project / 'codex'
    binary.write_text('#!' + sys.executable + '\n' + "import pathlib,sys\n"
                      "assert sys.argv[1] == 'exec'\n"
                      "assert '--ephemeral' in sys.argv\n"
                      "assert 'workspace-write' in sys.argv\n"
                      "assert 'Check evidence' in sys.stdin.read()\n"
                      "pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text('Default result')\n")
    binary.chmod(0o755)
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), 'step',
                             '-p', str(project), '--topic', 'research'], capture_output=True,
                            text=True, env={**os.environ, 'PATH': str(project) + os.pathsep + os.environ['PATH']})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['completed_rounds'] == 1
    assert (project / '.archa/topics/research/steps/step-01/result.md').read_text() == 'Default result'


def test_installed_cli_requires_topic_and_exposes_only_topic_commands(tmp_path):
    help_result = subprocess.run([sys.executable, '-m', 'opc', '--help'],
                                 capture_output=True, text=True, cwd=ROOT)
    assert help_result.returncode == 0
    assert 'resume' in help_result.stdout and 'report' in help_result.stdout
    assert 'promote' not in help_result.stdout and 'onboard' not in help_result.stdout
    result = subprocess.run([sys.executable, '-m', 'opc', 'init', '-p', str(tmp_path)],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode != 0 and '--topic' in result.stderr
    assert not (tmp_path / '.opc').exists()
