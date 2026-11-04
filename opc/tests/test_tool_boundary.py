"""Task tools run behind real filesystem and network boundaries, not cwd alone."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from opc.core.tool_boundary import tool_policy, runner_argv
from opc.tests.test_codex_and_config import fake_codex


def test_new_literal_deliverable_gets_only_its_exact_file_grant(tmp_path):
    tree = tmp_path / 'work'
    tree.mkdir()
    policy = tool_policy(tree, editable=['results/report.md'], protected=['results/frozen.md'])
    target = tree / 'results/report.md'
    assert target.is_file()
    assert str(target) in policy['write']
    assert str(target.parent) not in policy['write']
    assert not (tree / 'results/frozen.md').exists()


@pytest.mark.skipif(sys.platform != 'linux', reason='executes real Linux Landlock permission probes; unsupported-platform refusal covered separately')
def test_task_tool_can_change_editable_input_but_not_frozen_or_sibling(tmp_path):
    tree = tmp_path / 'work'
    tree.mkdir()
    (tree / 'editable.txt').write_text('before')
    (tree / 'frozen.txt').write_text('frozen')
    sibling = tmp_path / 'other-work'
    sibling.mkdir()
    (sibling / 'private.txt').write_text('private')
    policy = tool_policy(tree, editable=['editable.txt'], scratch=[], protected=['frozen.txt'])
    program = '''import json, os, socket
from pathlib import Path
Path('editable.txt').write_text('after')
blocked = []
for target in [Path('frozen.txt'), Path(%r)]:
    try:
        target.write_text('bad') if target.name == 'frozen.txt' else target.read_text()
    except PermissionError:
        blocked.append(target.name)
try:
    socket.socket()
except PermissionError:
    blocked.append('network')
print(json.dumps(blocked))
''' % str(sibling / 'private.txt')
    policy_path = tmp_path / 'policy.json'
    policy_path.write_text(json.dumps(policy))
    result = subprocess.run(runner_argv(policy_path, [str(Path(sys.executable).resolve()), '-c', program]),
                            cwd=tree, capture_output=True, text=True,
                            env={**os.environ, 'SECRET_TRANSPORT_TOKEN': 'must-not-reach-tool'})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ['frozen.txt', 'private.txt', 'network']
    assert (tree / 'editable.txt').read_text() == 'after'
    assert (tree / 'frozen.txt').read_text() == 'frozen'


def test_task_policy_refuses_symlink_escape_before_granting_or_creating_paths(tmp_path):
    tree, outside = tmp_path / 'task', tmp_path / 'outside'
    tree.mkdir(); outside.mkdir()
    (tree / 'src').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='escapes task workspace'):
        tool_policy(tree, editable=['src/new/**'])
    assert not (outside / 'new').exists()


def test_global_frozen_glob_never_grants_writable_containing_directory(tmp_path):
    tree = tmp_path / 'task'
    (tree / 'src').mkdir(parents=True)
    (tree / 'src' / 'locked.txt').write_text('frozen')
    policy = tool_policy(tree, editable=['src/**'], protected=['**/locked.txt'])
    assert str(tree / 'src') not in policy['write']
    assert policy['limitations']


def test_invalid_tool_scope_is_reported_as_not_started_not_unknown(tmp_path):
    from opc.adapters.codex import CodexWorker
    tree, outside = tmp_path / 'task', tmp_path / 'outside'
    tree.mkdir(); outside.mkdir()
    (tree / 'src').symlink_to(outside, target_is_directory=True)
    ctx = {'component': {'editable': ['src/**']}, 'task': {'goal': 'bounded work'}}
    call = CodexWorker({'binary': '/nonexistent/codex'}).implement(
        {'title': 'work', 'changes': 'work'}, ctx, tree, tmp_path / 'logs')
    assert not call.ok and call.extra['not_started'] and call.extra['usage_complete']
    assert not call.extra.get('execution_unknown')
    assert 'escapes task workspace' in call.error
    assert not list(outside.iterdir())


@pytest.mark.skipif(sys.platform != 'linux', reason='executes real Linux Landlock permission probes; unsupported-platform refusal covered separately')
def test_only_declared_dependency_artifact_is_readable_and_transport_env_is_absent(tmp_path):
    from opc.core.tool_boundary import worker_policy
    tree, evidence = tmp_path / 'work', tmp_path / 'evidence'
    tree.mkdir(); evidence.mkdir()
    artifact = evidence / 'input.txt'
    artifact.write_text('saved input')
    (evidence / 'other.txt').write_text('other branch')
    policy = worker_policy('designer', tree, tmp_path / 'logs',
                           {'handoff': {'inputs': [{'path': str(artifact)}]}})
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    program = '''import os,json
from pathlib import Path
p=Path(%r)
assert p.read_text() == 'saved input'
blocked=[]
for name, action in [('input-write',lambda:p.write_text('bad')),('other-read',lambda:p.with_name('other.txt').read_text())]:
    try: action()
    except PermissionError: blocked.append(name)
print(json.dumps([blocked, 'SECRET_TRANSPORT_TOKEN' in os.environ]))
''' % str(artifact)
    result = subprocess.run(runner_argv(path, [str(Path(sys.executable).resolve()), '-c', program]),
                            cwd=tree, capture_output=True, text=True,
                            env={**os.environ, 'SECRET_TRANSPORT_TOKEN': 'not-a-real-secret'})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [['input-write', 'other-read'], False]


def test_observer_exposes_the_actual_call_tool_policy_without_dispatch(make_project, engine_for, fake_codex):
    from opc.observer.adapter import ObserverAdapter
    from opc.tests.conftest import task
    t = task(workers={'expert': {'kind': 'codex', 'binary': fake_codex},
                      'designer': {'kind': 'codex', 'binary': fake_codex}})
    root = make_project(tsk=t)
    e = engine_for(root)
    e.run(max_attempts_now=1)
    before = (len(e.ledger.calls(e.run_id)), e.ledger.totals(e.run_id), e.ledger.control(e.run_id))
    observer = ObserverAdapter(root)
    overview = observer.overview()['data']
    refs = list(overview['unlinked_runs'])
    for revision in overview['unlinked_revisions']:
        refs += observer.task_revision(revision['id'])['data']['runs']
    run = next(observer.run(ref['id'])['data'] for ref in refs
               if observer.run(ref['id'])['data']['source_run_id'] == e.run_id)
    policies = []
    for ref in run['calls']:
        call = observer.call(ref['id'])['data']
        for artifact in call['artifacts']:
            if artifact.get('label') == 'tool-policy.json':
                policies.append(json.loads(observer.content(artifact['id'])['data']['content']))
    assert len(policies) == 2 and all(p['network'] is False for p in policies)
    assert all(root.as_posix() not in p['write'] for p in policies)
    assert before == (len(e.ledger.calls(e.run_id)), e.ledger.totals(e.run_id), e.ledger.control(e.run_id))


@pytest.mark.parametrize('flag', ['--yolo', '--full-auto', '-sdanger-full-access',
                                  '--dangerously-bypass-approvals-and-sandbox'])
def test_cli_flag_cannot_widen_task_tool_authority(tmp_path, flag):
    from opc.adapters.codex import CodexWorker
    call, _ = CodexWorker({'binary': '/nonexistent/codex', 'extra_args': [flag]})._run(
        'expert', 'bounded work', tmp_path, tmp_path / 'logs', 'read-only', None)
    assert not call.ok and call.extra['not_started']
    assert 'conflicts with task tool boundary: ' + flag in call.error
    assert not (tmp_path / 'logs' / 'expert-events.jsonl').exists()


def test_native_profile_initialization_failure_blocks_without_unknown_execution(make_project, engine_for, fake_codex):
    from opc.tests.conftest import task
    Path(fake_codex).write_text("import sys\nprint('thread/start failed: error creating thread: failed to load AGENTS.md instructions: fs sandbox helper failed: Not a directory', file=sys.stderr)\nraise SystemExit(1)\n")
    t = task(workers={'expert': {'kind': 'codex', 'binary': fake_codex},
                      'designer': {'kind': 'codex', 'binary': fake_codex}})
    e = engine_for(make_project(tsk=t))
    result = e.run(max_attempts_now=1)
    assert result['state'] == 'blocked'
    call = e.ledger.calls(e.run_id)[-1]
    assert call['state'] == 'not_started' and call['result']['usage_complete']
    assert call['result']['extra']['capability_gap']
    assert not e.ledger.open_attempts(e.run_id)


def test_unsupported_platform_refuses_unisolated_tools(monkeypatch):
    import opc.core.tool_boundary as boundary
    monkeypatch.setattr(boundary.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='refusing unisolated execution'):
        boundary.restrict([], [])
