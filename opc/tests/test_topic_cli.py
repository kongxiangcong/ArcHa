"""Topic behavior through the independently deployed project-local CLI."""
from opc.tests.worker_fixture import custom
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
    result = subprocess.run([sys.executable, str(ROOT / 'skills/archa-discuss/scripts/initialize.py'),
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
    config = {role: custom() for role in ('expert', 'executor')}
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


def test_commands_accept_prompt_path_and_stdin_with_file_results(project):
    cli(project, 'init', '--goal', 'Investigate evidence')
    script = project / 'worker.py'
    script.write_text("""import pathlib, sys
role, state, output, prompt, topic = sys.argv[1:]
assert 'Investigate evidence' in pathlib.Path(prompt).read_text()
if role == 'expert':
    current = (pathlib.Path(topic) / 'STATE.md').read_text()
    assert 'STATUS: IN_PROGRESS' in current
    pathlib.Path(state).write_text(current + '\\nEvidence reviewed.\\n')
    pathlib.Path(output).write_text('One focused question')
else:
    pathlib.Path(output).write_text('Actual observation\\n')
    print('Final chat is diagnostic only')
    print('Diagnostic only', file=sys.stderr)
""")
    config = {role: {'provider': 'custom', 'command': [sys.executable, str(script), role,
                '{state_file}', '{output_file}', '{prompt_file}', '{topic_dir}'], 'timeout_seconds': 5}
                for role in ('expert', 'executor')}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    assert cli(project, 'step')['next_action'] == 'executor'
    assert cli(project, 'step')['completed_rounds'] == 1
    step = project / '.archa/topics/research/steps/step-01'
    assert (step / 'result.md').read_text() == 'Actual observation\n'
    assert 'Diagnostic only' in (step / '.executor.log').read_text()


@pytest.mark.parametrize(('change', 'message'), [
    ({'preset': 'unknown'}, 'manual migration'),
    ({'provider': 'unknown'}, 'unknown provider'),
    ({'reasoning_effort': 'high'}, 'unsupported provider options'),
    ({'model': None}, 'model'),
    ({'timeout_seconds': float('inf')}, 'timeout_seconds'),
    ({'command': ['{model.attr}']}, 'unavailable template variable'),
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
    spec = {'provider': 'custom', 'command': [sys.executable, '-c', 'raise Exception("must not run")'],
            'timeout_seconds': 5}
    if 'preset' in change:
        spec.pop('command')
    spec.update(change)
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': spec, 'executor': custom()}))
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
    spec = {'provider': 'custom', 'command': [sys.executable, '-c', 'import pathlib, sys, time; ' + body, '{output_file}'],
            'timeout_seconds': .2}
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': custom(), 'executor': spec}))
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
    config = {'expert': custom(), 'executor': {'provider': 'custom',
        'command': [sys.executable, '-c', "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('failed output'); sys.exit(1)", '{output_file}'],
        'timeout_seconds': 5}}
    path = project / '.archa/workers.json'
    path.write_text(json.dumps(config))
    cli(project, 'step', ok=False)
    config['executor']['command'] = [sys.executable, '-c', 'pass']
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
    config = {'expert': custom(), 'executor': {'provider': 'custom',
        'command': [sys.executable, str(script), '{output_file}'],
        'timeout_seconds': 1}}
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
def test_missing_project_config_uses_distributed_codex_provider(project):
    cli(project, 'init', '--goal', 'Check evidence')
    scripted(project)
    cli(project, 'step')
    (project / '.archa/workers.json').unlink()
    # Exercise the deployed default through a real executable, without model access.
    binary = project / 'codex'
    binary.write_text('#!' + sys.executable + '\n' + "import pathlib,re,sys\n"
                      "assert sys.argv[1] == 'exec'\n"
                      "assert '--ephemeral' in sys.argv\n"
                      "assert '--json' in sys.argv\n"
                      "assert '-s' not in sys.argv\n"
                      "prompt = sys.stdin.read()\n"
                      "assert 'Check evidence' in prompt\n"
                      "output = re.search(r'Write complete result to (.+)\\.', prompt)[1]\n"
                      "pathlib.Path(output).write_text('Default result')\n")
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


@pytest.mark.parametrize('finalize', [False, True])
def test_expert_must_write_state_before_publishing(project, finalize):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '1')
    scripted(project)
    if finalize:
        cli(project, 'step')
        cli(project, 'step')
    topic = project / '.archa/topics/research'
    before = (topic / 'STATE.md').read_bytes()
    body = "print('Expert exited without updating state', flush=True)"
    if not finalize:
        body += "; import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('Probe only')"
    spec = {'provider': 'custom', 'command': [sys.executable, '-c', body, '{output_file}'],
            'timeout_seconds': 5}
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': spec, 'executor': custom()}))
    assert 'missing or blank required output' in cli(project, 'step', ok=False)
    assert (topic / 'STATE.md').read_bytes() == before
    status = cli(project, 'status')
    assert status['status'] == 'IN_PROGRESS'
    assert status['next_action'] == ('expert_finalize' if finalize else 'expert')
    step = topic / 'steps/step-01'
    if not finalize:
        assert not (step / 'probe.md').exists()
    log = step / ('.expert_finalize.log' if finalize else '.expert.log')
    assert 'Expert exited without updating state' in log.read_text()


@pytest.mark.parametrize('configured', [False, True])
def test_codex_file_outputs_survive_final_chat_summary(project, tmp_path, monkeypatch, configured):
    """Codex's final chat message must not replace Worker-authored documents."""
    executable = tmp_path / 'bin'
    executable.mkdir()
    worker = executable / 'worker.py'
    expected = '''import os, sys
assert os.environ['ARCHA_HOST_TEST'] == 'inherited'
assert '--json' in sys.argv and '-s' not in sys.argv
'''
    if configured:
        expected += '''assert sys.argv[sys.argv.index('--model') + 1] == 'test-model'
assert sys.argv[sys.argv.index('-c') + 1] == 'model_reasoning_effort=\"high\"'
assert os.environ['ARCHA_OVERRIDE_TEST'] == 'configured'
'''
    else:
        expected += "assert '--model' not in sys.argv and '-c' not in sys.argv\n"
    monkeypatch.setenv('ARCHA_HOST_TEST', 'inherited')
    monkeypatch.setenv('ARCHA_OVERRIDE_TEST', 'host')
    if configured:
        config = {role: {'provider': 'codex', 'model': 'test-model', 'reasoning_effort': 'high',
                  'env': {'ARCHA_OVERRIDE_TEST': 'configured'}} for role in ('expert', 'executor')}
        (project / '.archa/workers.json').write_text(json.dumps(config))
    worker.write_text(expected + '''import pathlib, re, sys
prompt = sys.stdin.read()
role = prompt.splitlines()[0]
state = re.search(r"Write complete state to (.+)\\.", prompt)
if state:
    path = pathlib.Path(state[1])
    completed = 'expert_finalize' in role
    status = 'COMPLETED' if completed else 'IN_PROGRESS'
    path.write_text('# Exploration State\\nSTATUS: ' + status + '\\nMAX_ROUNDS: 1\\n\\nObserved exact integer mismatch.')
    probe = re.search(r"write one probe to (.+?)\\. COMPLETED", prompt)
    if probe:
        pathlib.Path(probe[1]).write_text('Compare [9007199254740993] to exact integer sum.')
else:
    result = re.search(r"Write complete result to (.+)\\.", prompt)
    pathlib.Path(result[1]).write_text('Input [9007199254740993]; expected 9007199254740993; actual 9007199254740992.')
if '-o' in sys.argv:
    pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_text('Done; see the file I wrote.')
print('Done; see the file I wrote.')
''')
    if os.name == 'nt':
        (executable / 'codex.cmd').write_text(f'@"{sys.executable}" "{worker}" %*\n')
    else:
        launcher = executable / 'codex'
        launcher.write_text(f'#!{sys.executable}\nexec(compile(open({str(worker)!r}).read(), {str(worker)!r}, "exec"))\n')
        launcher.chmod(0o755)
    monkeypatch.setenv('PATH', str(executable) + os.pathsep + os.environ['PATH'])
    cli(project, 'init', '--goal', 'Observe exact integer semantics', '--max-rounds', '1')
    cli(project, 'step')
    topic = project / '.archa/topics/research'
    assert (topic / 'steps/step-01/probe.md').read_text() == 'Compare [9007199254740993] to exact integer sum.'
    cli(project, 'step')
    assert (topic / 'steps/step-01/result.md').read_text() == 'Input [9007199254740993]; expected 9007199254740993; actual 9007199254740992.'
    assert cli(project, 'step')['status'] == 'COMPLETED'
    assert 'Observed exact integer mismatch.' in (topic / 'STATE.md').read_text()


def test_deployed_probe_breakpoints_continue_and_finalize(project):
    cli(project, 'init', '--goal', 'Inspect evidence', '--max-rounds', '2')
    scripted(project)
    first = cli(project, 'run', '--debug-probes')
    assert first['probe_breakpoint'] and first['completed_rounds'] == 0
    assert first['activity'] == 'idle' and first['error'] is None
    assert cli(project, 'status')['probe_breakpoint']
    second = cli(project, 'resume')
    assert second['probe_breakpoint'] and second['completed_rounds'] == 1
    assert second['current_round'] == 2
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), 'resume',
                             '-p', str(project), '--topic', 'research'], capture_output=True, text=True)
    assert result.returncode == 5, result.stderr
    final = json.loads(result.stdout)
    assert final['status'] == 'BUDGET_EXHAUSTED' and final['completed_rounds'] == 2
    assert not final['probe_breakpoint']


@pytest.mark.parametrize('terminal', ['COMPLETED', 'BLOCKED'])
def test_debug_probes_preserves_expert_terminal_decision(project, terminal):
    cli(project, 'init', '--goal', 'Inspect evidence')
    body = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_text(pathlib.Path(sys.argv[2]).read_text().replace('IN_PROGRESS', sys.argv[3]))"
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': {'provider': 'custom', 'command': [sys.executable, '-c', body, '{state_file}',
                              '{topic_dir}/STATE.md', terminal],
                   'timeout_seconds': 5},
        'executor': custom()}))
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), 'run',
                             '-p', str(project), '--topic', 'research', '--debug-probes'],
                            capture_output=True, text=True)
    assert result.returncode == (0 if terminal == 'COMPLETED' else 4), result.stderr
    status = json.loads(result.stdout)
    assert status['status'] == terminal and status['completed_rounds'] == 0
    assert not status['probe_breakpoint'] and status['error'] is None


def test_enabling_debug_holds_existing_probe_and_step_stays_single_dispatch(project):
    cli(project, 'init', '--goal', 'Inspect evidence', '--max-rounds', '3')
    scripted(project)
    cli(project, 'step')
    assert cli(project, 'resume', '--debug-probes')['completed_rounds'] == 0
    result = cli(project, 'step')
    assert result['completed_rounds'] == 1 and result['next_action'] == 'expert'
    result = cli(project, 'resume')
    assert result['probe_breakpoint'] and result['completed_rounds'] == 1


def test_deployed_revise_preserves_round_and_failed_proposal(project):
    cli(project, 'init', '--goal', 'Inspect evidence', '--max-rounds', '3')
    scripted(project)
    cli(project, 'run', '--debug-probes')
    topic = project / '.archa/topics/research'
    original = (topic / 'steps/step-01/probe.md').read_text()
    worker = project / 'revise.py'
    worker.write_text("""import pathlib, sys
state, output = map(pathlib.Path, sys.argv[1:])
text = sys.stdin.read()
assert 'CURRENT PROBE\\n# Probe' in text and 'Inspect evidence' in text
assert 'USER DIRECTION' in text and 'Focus on the baseline' in text
assert 'already reflected in STATE' in text
state.write_text(state.parents[3].joinpath('STATE.md').read_text())
output.write_text('Revised baseline probe')
""")
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': {'provider': 'custom', 'command': [sys.executable, str(worker), '{state_file}', '{output_file}'],
                   'timeout_seconds': 5},
        'executor': custom()}))
    revised = cli(project, 'revise', '--feedback', 'Focus on the baseline')
    assert revised['probe_breakpoint'] and revised['current_round'] == 1
    assert revised['completed_rounds'] == 0 and revised['max_rounds'] == 3
    step = topic / 'steps/step-01'
    assert (step / 'probe.md').read_text() == 'Revised baseline probe' != original
    assert not (step / 'result.md').exists()
    worker.write_text("import pathlib,sys; pathlib.Path(sys.argv[2]).write_text('partial'); sys.exit(7)")
    assert 'code 7' in cli(project, 'revise', '--feedback', 'Try again', ok=False)
    assert (step / 'probe.md').read_text() == 'Revised baseline probe'
    assert not (step / 'result.md').exists()
    assert cli(project, 'status')['error']


def test_deployed_expert_receives_probe_hypothesis_and_evidence_contract(project):
    cli(project, 'init', '--goal', 'Inspect integer precision', '--max-rounds', '2')
    worker = project / 'expert.py'
    worker.write_text("""import pathlib, sys
state, output, topic = map(pathlib.Path, sys.argv[1:])
text = sys.stdin.read()
assert 'A continuing probe must include the current hypothesis and its supporting' in text
assert 'evidence or rationale' in text
state.write_text((topic / 'STATE.md').read_text())
output.write_text('# Hypothesis\\nFloat conversion loses integer precision.\\n\\n'
                  '## Evidence\\nBaseline 9007199254740993 became 9007199254740992.\\n\\n'
                  '## Probe\\nCompare exact integer addition with the baseline.')
""")
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': {'provider': 'custom', 'command': [sys.executable, str(worker), '{state_file}', '{output_file}', '{topic_dir}'],
                   'timeout_seconds': 5},
        'executor': custom()}))
    assert cli(project, 'run', '--debug-probes')['probe_breakpoint']
    assert cli(project, 'revise', '--feedback', 'Keep the measured baseline')['probe_breakpoint']
    assert cli(project, 'resume')['current_round'] == 2


def test_custom_provider_uses_stdin_and_file_outputs(project):
    cli(project, 'init', '--goal', 'Check evidence')
    body = "import pathlib,sys; text=sys.stdin.read(); assert 'Check evidence' in text; pathlib.Path(sys.argv[1]).write_text(pathlib.Path(sys.argv[3]).read_text()); pathlib.Path(sys.argv[2]).write_text('Probe from stdin')"
    config = {role: {'provider': 'custom', 'command': [sys.executable, '-c', body,
              '{state_file}', '{output_file}', '{topic_dir}/STATE.md']} for role in ('expert', 'executor')}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    assert cli(project, 'step')['next_action'] == 'executor'
    assert cli(project, 'step')['completed_rounds'] == 1
    assert not list((project / '.archa/topics').rglob('*.prompt.md'))


@pytest.mark.parametrize('legacy', [
    {'roles': {'expert': {'preset': 'codex'}, 'executor': {'preset': 'codex'}}},
    {'expert': {'preset': 'scripted'}, 'executor': {'preset': 'scripted'}},
])
def test_old_worker_configuration_requires_manual_migration(project, legacy):
    cli(project, 'init', '--goal', 'Check evidence')
    path = project / '.archa/workers.json'
    path.write_text(json.dumps(legacy))
    original = path.read_bytes()
    assert 'manual migration' in cli(project, 'check', ok=False)
    assert 'manual migration' in cli(project, 'step', ok=False)
    assert path.read_bytes() == original
    assert not list((project / '.archa/topics').rglob('probe.md'))


def test_custom_long_stdin_environment_model_and_prompt_cleanup(project, monkeypatch):
    cli(project, 'init', '--goal', 'Long evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Long evidence\n' + '证据' * 70000)
    monkeypatch.setenv('ARCHA_HOST_TEST', 'inherited')
    monkeypatch.setenv('ARCHA_OVERRIDE_TEST', 'host')
    worker = project / 'long.py'
    worker.write_text("""import os, pathlib, sys
text = sys.stdin.read()
assert len(text.encode()) > 131072 and '证据' in text
assert text == pathlib.Path(sys.argv[4]).read_text()
assert sys.argv[5] == 'chosen-model'
assert os.environ['ARCHA_HOST_TEST'] == 'inherited'
assert os.environ['ARCHA_OVERRIDE_TEST'] == 'configured'
assert pathlib.Path.cwd() == pathlib.Path(sys.argv[6])
pathlib.Path(sys.argv[1]).write_text(pathlib.Path(sys.argv[3]).read_text())
pathlib.Path(sys.argv[2]).write_text('Long stdin probe')
""")
    spec = {'provider': 'custom', 'model': 'chosen-model', 'env': {'ARCHA_OVERRIDE_TEST': 'configured'},
            'command': [sys.executable, str(worker), '{state_file}', '{output_file}',
                        '{topic_dir}/STATE.md', '{prompt_file}', '{model}', '{workdir}']}
    (project / '.archa/workers.json').write_text(json.dumps({'expert': spec, 'executor': custom()}))
    assert cli(project, 'step')['next_action'] == 'executor'
    assert not list(topic.rglob('*.prompt.md'))
    assert (topic / 'steps/step-01/probe.md').read_text() == 'Long stdin probe'


def test_deployed_lifecycle_distinguishes_process_and_publication(project):
    cli(project, 'init', '--goal', 'Lifecycle', '--max-rounds', '1')
    scripted(project)
    cli(project, 'step')
    step = project / '.archa/topics/research/steps/step-01'
    events = [json.loads(line) for line in (step / '.expert.events.jsonl').read_text().splitlines()]
    assert [event['title'] for event in events] == ['started', 'completed']
    assert set(events[0]) == {'seq', 'ts', 'kind', 'title', 'status', 'detail'}
    assert 'custom' in events[0]['detail']
    config = {'expert': custom(), 'executor': {'provider': 'custom', 'command': [sys.executable, '-c', 'print("no artifact")']}}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    assert 'missing or blank' in cli(project, 'step', ok=False)
    events = [json.loads(line) for line in (step / '.executor.events.jsonl').read_text().splitlines()]
    assert events[-1]['title'] == 'completed'
    assert 'exit_code=0' in events[-1]['detail']
    assert not (step / 'result.md').exists()


@pytest.mark.parametrize(('body', 'outcome'), [
    ('import sys; sys.exit(7)', 'failed'),
    ('import time; time.sleep(10)', 'timed_out'),
])
def test_deployed_process_failure_trace(project, body, outcome):
    cli(project, 'init', '--goal', 'Trace failures')
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': {'provider': 'custom', 'command': [sys.executable, '-c', body], 'timeout_seconds': .1},
        'executor': custom()}))
    cli(project, 'step', ok=False)
    step = project / '.archa/topics/research/steps/step-01'
    events = [json.loads(line) for line in (step / '.expert.events.jsonl').read_text().splitlines()]
    assert events[-1]['title'] == outcome and events[-1]['status'] == 'error'
    assert not (step / 'probe.md').exists()


def test_deployed_trace_failure_does_not_prevent_publication(project):
    cli(project, 'init', '--goal', 'Trace fault')
    scripted(project)
    step = project / '.archa/topics/research/steps/step-01'
    step.mkdir()
    # File boundary failure: the event destination cannot be atomically replaced.
    (step / '.expert.events.jsonl').mkdir()
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), 'step', '-p', str(project), '--topic', 'research'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'Telemetry incomplete:' in result.stderr
    assert 'Telemetry incomplete:' in (step / '.expert.log').read_text()
    assert (step / 'probe.md').exists()


def test_deployed_four_roles_replace_only_their_own_stream(project):
    cli(project, 'init', '--goal', 'Four roles', '--max-rounds', '1')
    scripted(project)
    cli(project, 'run', '--debug-probes')
    step = project / '.archa/topics/research/steps/step-01'
    expert = (step / '.expert.events.jsonl').read_bytes()
    for attempt in range(2):
        cli(project, 'revise', '--feedback', 'Keep the baseline')
        events = [json.loads(line) for line in (step / '.expert_revise.events.jsonl').read_text().splitlines()]
        assert [event['seq'] for event in events] == [1, 2]
        if attempt:
            assert events[0]['ts'] != previous
        previous = events[0]['ts']
    cli(project, 'step')
    cli(project, 'step')
    assert (step / '.expert.events.jsonl').read_bytes() == expert
    for role in ('expert', 'executor', 'expert_revise', 'expert_finalize'):
        events = [json.loads(line) for line in (step / f'.{role}.events.jsonl').read_text().splitlines()]
        assert events[-1]['title'] == 'completed'
    assert not (step.parent / 'step-02').exists()
