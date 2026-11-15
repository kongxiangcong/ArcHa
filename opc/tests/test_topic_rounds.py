"""Round scheduling through the deployed project-local CLI."""
from opc.tests.test_topic_cli import project, cli, scripted


def test_last_round_is_digested_without_dispatching_another_probe(project):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '1')
    scripted(project)
    cli(project, 'step')
    cli(project, 'step')
    before = project / '.archa/topics/research/steps/step-01/.expert.log'
    original = before.read_text()
    result = cli(project, 'step')
    assert result['status'] == 'BUDGET_EXHAUSTED'
    assert result['completed_rounds'] == 1
    assert result['current_round'] == 1
    assert before.read_text() == original
    assert before.with_name('.expert_finalize.log').is_file()
    assert not before.parent.with_name('step-02').exists()


def execute(project, command, *args, code):
    import subprocess
    import sys
    import json
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), command,
                             '-p', str(project), '--topic', 'research', *args],
                            cwd=project, capture_output=True, text=True)
    assert result.returncode == code, (result.stdout, result.stderr)
    return json.loads(result.stdout)


def test_run_and_additional_budget_preserve_completed_rounds(project):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '2')
    scripted(project)
    result = execute(project, 'run', code=5)
    assert result['completed_rounds'] == 2
    topic = project / '.archa/topics/research'
    original = (topic / 'steps/step-01/result.md').read_bytes()
    result = execute(project, 'resume', '--add-rounds', '1', code=5)
    assert result['max_rounds'] == 3
    assert result['completed_rounds'] == 3
    assert (topic / 'steps/step-01/result.md').read_bytes() == original
    assert not (topic / 'steps/step-04').exists()
    assert execute(project, 'resume', code=5)['completed_rounds'] == 3
    assert 'positive integer' in cli(project, 'resume', '--add-rounds', '0', ok=False)


def worker(project, body):
    import json
    import sys
    script = project / 'decisions.py'
    script.write_text('import sys\nfrom pathlib import Path\n'
                      'state, output, topic = map(Path, sys.argv[1:])\n'
                      'prompt = sys.stdin.read()\n' + body)
    (project / '.archa/workers.json').write_text(json.dumps({'roles': {
        'expert': {'command': [sys.executable, str(script), '{state_file}', '{output_file}', '{topic_dir}'],
                   'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 5},
        'executor': {'preset': 'scripted'}}}))


def test_blocked_topic_requires_explicit_resume_and_completed_topic_stays_closed(project):
    cli(project, 'init', '--goal', 'Verify the evidence')
    worker(project, """
assert 'alternative' in prompt
assert 'hypotheses' in prompt
assert 'conditions' in prompt
assert 'tests required by the goal' in prompt
status = 'COMPLETED' if (topic / 'conditions-ready').exists() else 'BLOCKED'
state.write_text(state.read_text().replace('STATUS: IN_PROGRESS', 'STATUS: ' + status)
                 + '\\nNeed access to evidence; no alternative path.\\n')
""")
    assert execute(project, 'run', code=4)['completed_rounds'] == 0
    topic = project / '.archa/topics/research'
    (topic / 'conditions-ready').touch()
    assert execute(project, 'run', code=4)['status'] == 'BLOCKED'
    assert execute(project, 'resume', code=0)['status'] == 'COMPLETED'
    assert cli(project, 'status')['completed_rounds'] == 0
    before = (topic / 'STATE.md').read_bytes()
    assert 'COMPLETED' in cli(project, 'resume', '--add-rounds', '1', ok=False)
    assert execute(project, 'run', code=0)['status'] == 'COMPLETED'
    assert (topic / 'STATE.md').read_bytes() == before
    assert not (topic / 'steps/step-01/probe.md').exists()


def test_domain_neutral_default_and_optional_pim_template(project):
    cli(project, 'init', '--goal', 'Trace a citation')
    topic = project / '.archa/topics/research'
    assert 'PIM' not in (topic / 'GOAL.md').read_text()
    assert 'simulator' not in (topic / 'STATE.md').read_text()
    cli(project, 'init', '--topic', 'hardware', '--goal', 'Check mapping', '--template', 'pim')
    goal = (topic.parent / 'hardware/GOAL.md').read_text()
    assert 'PIM' in goal
    assert 'Check mapping' in goal
    cli(project, 'init', '--topic', 'empty-pim', '--template', 'pim')
    assert 'GOAL.md is empty' in cli(project, 'step', '--topic', 'empty-pim', ok=False)


def test_finalize_can_complete_and_context_excludes_old_rounds_and_logs(project):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '2')
    scripted(project)
    cli(project, 'step')
    cli(project, 'step')
    cli(project, 'step')
    cli(project, 'step')
    topic = project / '.archa/topics/research'
    (topic / 'steps/step-01/result.md').write_text('OLD_RESULT_MUST_NOT_BE_INJECTED')
    (topic / 'steps/step-02/.executor.log').write_text('LOG_MUST_NOT_BE_INJECTED')
    worker(project, """
assert 'OLD_RESULT_MUST_NOT_BE_INJECTED' not in prompt
assert 'LOG_MUST_NOT_BE_INJECTED' not in prompt
assert 'PREVIOUS result.md' in prompt and 'Observed the current probe' in prompt
assert 'Role: expert_finalize' in prompt
assert 'Do not create a probe' in prompt
state.write_text(state.read_text().replace('STATUS: IN_PROGRESS', 'STATUS: COMPLETED')
                 + '\\nEvidence supports the completion criteria.\\n')
""")
    result = execute(project, 'run', code=0)
    assert result['status'] == 'COMPLETED'
    assert result['completed_rounds'] == 2
    assert not (topic / 'steps/step-03').exists()


def test_resume_reuses_absorbed_fact_and_negative_result_without_retry(project):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '1')
    worker(project, """
text = state.read_text()
assert 'without counting the same observation again' in prompt
if 'PREVIOUS result.md' in prompt and 'Unique fact: negative observation.' not in text:
    text += '\\nUnique fact: negative observation.\\n'
state.write_text(text)
if state != output:
    output.write_text('Test the single mechanism')
""")
    import json
    import sys
    config_path = project / '.archa/workers.json'
    config = json.loads(config_path.read_text())
    config['roles']['executor'] = {'command': [sys.executable, '-c', "print('Negative observation: intervention did not improve the result.')"],
                                   'input_mode': 'stdin', 'output_mode': 'stdout', 'timeout_seconds': 5}
    config_path.write_text(json.dumps(config))
    execute(project, 'run', code=5)
    topic = project / '.archa/topics/research'
    first = (topic / 'steps/step-01/result.md').read_bytes()
    execute(project, 'resume', '--add-rounds', '1', code=5)
    assert (topic / 'STATE.md').read_text().count('Unique fact: negative observation.') == 1
    assert (topic / 'steps/step-01/result.md').read_bytes() == first
    assert cli(project, 'status')['completed_rounds'] == 2


def test_run_failure_stops_once_without_domain_blocking(project):
    cli(project, 'init', '--goal', 'Check evidence')
    worker(project, """
with (topic / 'worker-effects').open('a') as f:
    f.write('started\\n')
raise SystemExit(7)
""")
    assert 'code 7' in cli(project, 'run', ok=False)
    topic = project / '.archa/topics/research'
    assert (topic / 'worker-effects').read_text() == 'started\n'
    status = cli(project, 'status')
    assert status['status'] == 'IN_PROGRESS'
    assert status['completed_rounds'] == 0


def test_lowered_budget_never_dispatches_committed_pending_probe(project):
    cli(project, 'init', '--goal', 'Check evidence', '--max-rounds', '3')
    scripted(project)
    for _ in range(3):
        cli(project, 'step')
    topic = project / '.archa/topics/research'
    state = topic / 'STATE.md'
    state.write_text(state.read_text().replace('MAX_ROUNDS: 3', 'MAX_ROUNDS: 1'))
    before = state.read_bytes()
    assert 'pending probe' in cli(project, 'run', ok=False)
    assert state.read_bytes() == before
    assert not (topic / 'steps/step-02/result.md').exists()
