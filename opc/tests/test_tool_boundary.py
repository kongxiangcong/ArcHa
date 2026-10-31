"""Task tools run behind real filesystem and network boundaries, not cwd alone."""
import json
import os
from pathlib import Path
import subprocess
import sys

from opc.core.tool_boundary import tool_policy, runner_argv


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
    import pytest
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
