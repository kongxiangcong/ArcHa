"""DSH file protocol through the installed CLI and real subprocess boundary."""
import json
import os
import sys

import pytest

from opc.tests.test_topic_cli import cli, project

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")


def providers(project, monkeypatch, expert, model='chosen-model'):
    binary = project / 'bin'
    binary.mkdir(exist_ok=True)
    source = '''import json, os, pathlib, re, sys, time
provider = pathlib.Path(sys.argv[0]).name
assert sys.argv[-1] == '-'
assert '--json' in sys.argv
assert os.environ['ARCHA_OVERRIDE_TEST'] == 'configured'
if provider == 'dsh':
    assert sys.argv[1:3] == ['--profile', 'headless']
    assert '--model' not in sys.argv
    if os.environ['EXPECTED_MODEL']:
        patch = pathlib.Path(sys.argv[sys.argv.index('--patch') + 1]).read_text()
        assert 'model: ' + json.dumps(os.environ['EXPECTED_MODEL']) in patch
        assert 'inject: [archaModelOverride]' in patch
    else:
        assert '--patch' not in sys.argv
prompt = sys.stdin.read()
assert len(prompt.encode()) > 131072
role = prompt.splitlines()[0].removeprefix('Role: ')
print(json.dumps({'type': 'final', 'text': 'Diagnostic only', 'provider': provider, 'role': role}), flush=True)
mode = os.environ.get('FAILURE', '')
if mode == 'exit': sys.exit(7)
if mode == 'missing': sys.exit(0)
if mode == 'timeout': time.sleep(10)
state = re.search(r'Write complete state to (.+)\\.', prompt)
if state:
    path = pathlib.Path(state[1])
    text = pathlib.Path('.archa/topics/research/STATE.md').read_text()
    if mode == 'invalid': text = '# Exploration State\\nSTATUS: NONSENSE\\nMAX_ROUNDS: 1\\n\\n'
    path.write_text(text + '\\nAbsorbed prior evidence.\\n')
    probe = re.search(r'write one probe to (.+?)\\. COMPLETED', prompt)
    if probe: pathlib.Path(probe[1]).write_text('Focused probe ' + provider)
else:
    output = re.search(r'Write complete result to (.+)\\.', prompt)[1]
    pathlib.Path(output).write_text('Observation from ' + provider)
'''
    for name in ('codex', 'dsh'):
        path = binary / name
        path.write_text('#!' + sys.executable + '\n' + source)
        path.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary) + os.pathsep + os.environ['PATH'])
    config = {role: {'provider': name, 'model': model,
                    'env': {'ARCHA_OVERRIDE_TEST': 'configured', 'EXPECTED_MODEL': model}}
              for role, name in [('expert', expert), ('executor', 'codex' if expert == 'dsh' else 'dsh')]}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    return config


@pytest.mark.parametrize('expert', ['codex', 'dsh'])
def test_cross_provider_long_stdin_revise_finalize_and_switch(project, monkeypatch, expert):
    cli(project, 'init', '--goal', 'Evidence', '--max-rounds', '1')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    providers(project, monkeypatch, expert)
    cli(project, 'run', '--debug-probes')
    cli(project, 'revise', '--feedback', 'Refine hypothesis')
    assert cli(project, 'step')['completed_rounds'] == 1
    original = (topic / 'steps/step-01/result.md').read_bytes()
    assert cli(project, 'step')['status'] == 'BUDGET_EXHAUSTED'
    for role in ('expert', 'expert_revise', 'expert_finalize'):
        log = (topic / 'steps/step-01' / ('.' + role + '.log')).read_text()
        assert json.loads(log)['provider'] == expert
    providers(project, monkeypatch, 'codex' if expert == 'dsh' else 'dsh', model='')
    assert cli(project, 'resume', '--add-rounds', '1')['completed_rounds'] == 1
    assert cli(project, 'step')['completed_rounds'] == 2
    assert (topic / 'steps/step-01/result.md').read_bytes() == original
    assert 'Absorbed prior evidence.' in (topic / 'STATE.md').read_text()
    assert not list(topic.rglob('*.prompt.md'))
    assert not list(topic.rglob('*.provider.yml'))
    assert not list(topic.rglob('*.provider.mjs'))


@pytest.mark.parametrize(('failure', 'message'), [('exit', 'code 7'), ('missing', 'missing'),
                                                  ('invalid', 'invalid STATUS'), ('timeout', 'timed out')])
def test_dsh_failures_preserve_state_and_recover(project, monkeypatch, failure, message):
    cli(project, 'init', '--goal', 'Evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    config = providers(project, monkeypatch, 'dsh')
    before = (topic / 'STATE.md').read_bytes()
    config['expert']['env']['FAILURE'] = failure
    config['expert']['timeout_seconds'] = .2
    (project / '.archa/workers.json').write_text(json.dumps(config))
    assert message in cli(project, 'step', ok=False)
    assert (topic / 'STATE.md').read_bytes() == before
    assert cli(project, 'status')['status'] == 'IN_PROGRESS'
    assert not (topic / 'steps/step-01/probe.md').exists()
    assert not list(topic.rglob('*.provider.yml'))
    assert not list(topic.rglob('*.provider.mjs'))
    assert 'Diagnostic only' in (topic / 'steps/step-01/.expert.log').read_text()
    providers(project, monkeypatch, 'dsh')
    assert cli(project, 'step')['next_action'] == 'executor'


def test_dsh_rejects_codex_only_option_before_dispatch(project):
    cli(project, 'init', '--goal', 'Evidence')
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': {'provider': 'dsh', 'reasoning_effort': 'high'},
        'executor': {'provider': 'codex'}}))
    assert 'expert: unknown fields or unsupported provider options: reasoning_effort' in cli(project, 'check', ok=False)


@pytest.mark.skipif(not os.environ.get('ARCHA_TEST_DSH'), reason='opt-in native DSH startup, no model request')
def test_native_dsh_override_preserves_provider_and_effort(project, monkeypatch):
    cli(project, 'init', '--goal', 'Synthetic native config smoke')
    baseline = project / 'baseline.yml'
    baseline.write_text('''- id: agent-default-model
  config:
    provider: !!js "'fixture-provider'"
    model: original-model
    reasoningEffort: fixture-effort
- id: headless-runner
  config:
    json: true
    task: !!js |
      (() => {
        const value = ctx.agentDefaultModel.currentSelection();
        if (value.provider !== 'fixture-provider' || value.reasoningEffort !== 'fixture-effort' || value.model !== 'chosen-model') throw new Error('MODEL_CONFIG_NOT_PRESERVED');
        return '';
      })()
''')
    binary = project / 'dsh'
    binary.write_text('#!' + sys.executable + '\nimport subprocess,sys\n'
                      'sys.stdin.read()\n'
                      + f'raise SystemExit(subprocess.call([{os.environ["ARCHA_TEST_DSH"]!r}, "--patch", {str(baseline)!r}, *sys.argv[1:]], stdin=subprocess.DEVNULL))\n')
    binary.chmod(0o755)
    monkeypatch.setenv('PATH', str(project) + os.pathsep + os.environ['PATH'])
    (project / '.archa/workers.json').write_text(json.dumps({
        'expert': {'provider': 'dsh', 'model': 'chosen-model', 'timeout_seconds': 30},
        'executor': {'provider': 'codex'}}))
    assert 'code 1' in cli(project, 'step', ok=False)
    topic = project / '.archa/topics/research'
    log = (topic / 'steps/step-01/.expert.log').read_text()
    assert 'a task is required' in log, log
    assert 'MODEL_CONFIG_NOT_PRESERVED' not in log
    assert not list(topic.rglob('*.provider.*'))


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /dev/full write failure")
def test_dsh_patch_write_failure_cleans_up_and_preserves_error(project, monkeypatch):
    cli(project, 'init', '--goal', 'Evidence')
    providers(project, monkeypatch, 'dsh')
    topic = project / '.archa/topics/research'
    step = topic / 'steps/step-01'
    step.mkdir(parents=True, exist_ok=True)
    (step / '.expert.prompt.provider.yml').symlink_to('/dev/full')
    assert 'No space left on device' in cli(project, 'step', ok=False)
    assert not list(topic.rglob('*.provider.*'))
    assert not (step / 'probe.md').exists()
