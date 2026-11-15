"""Control behavior through deployed CLI and real concurrent processes."""
import json
import os
import subprocess
import sys
import time

from opc.tests.test_topic_cli import cli, project, scripted


def start(project, topic='research'):
    return subprocess.Popen([sys.executable, str(project / '.archa/archa.py'), 'step',
                             '-p', str(project), '--topic', topic],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def long_executor(project):
    cli(project, 'init', '--goal', 'Check evidence')
    scripted(project)
    cli(project, 'step')
    command = "import pathlib,time; pathlib.Path('side-effect').write_text('preserved'); print('running now', flush=True); time.sleep(30)"
    config = {'roles': {'expert': {'preset': 'scripted'}, 'executor': {
        'command': [sys.executable, '-c', command], 'input_mode': 'stdin',
        'output_mode': 'stdout', 'timeout_seconds': 40}}}
    (project / '.archa/workers.json').write_text(json.dumps(config))


def wait_running(project):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if (project / 'side-effect').exists():
            return cli(project, 'status')
        time.sleep(.01)
    raise AssertionError('worker did not start')


def test_stop_waits_then_edit_pending_probe_and_retry(project):
    long_executor(project)
    process = start(project)
    try:
        assert wait_running(project)['activity'] == 'running'
        stopped = cli(project, 'stop')
        assert stopped['activity'] == 'idle'
        process.communicate(timeout=5)
        assert process.returncode != 0
        assert cli(project, 'stop')['activity'] == 'idle'
        assert 'running now' in (project / '.archa/topics/research/steps/step-01/.executor.log').read_text()
        probe = project / '.archa/topics/research/steps/step-01/probe.md'
        probe.write_text('Human corrected question')
        scripted(project)
        assert cli(project, 'step')['completed_rounds'] == 1
        assert 'Human corrected question' in probe.with_name('result.md').read_text()
        assert (project / 'side-effect').read_text() == 'preserved'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_crashed_controller_recovers_owned_worker_before_retry(project):
    long_executor(project)
    process = start(project)
    wait_running(project)
    process.kill()
    process.wait(timeout=5)
    assert cli(project, 'status')['activity'] == 'unknown'
    scripted(project)
    assert cli(project, 'step')['completed_rounds'] == 1
    assert cli(project, 'status')['activity'] == 'idle'


def test_competing_topics_and_stale_stop_do_not_affect_new_execution(project):
    long_executor(project)
    cli(project, 'init', '--topic', 'other', '--goal', 'Other question')
    process = start(project)
    try:
        first = wait_running(project)['execution']['id']
        assert 'lock is held' in cli(project, 'step', ok=False)
        assert 'lock is held' in cli(project, 'step', '--topic', 'other', ok=False)
        assert cli(project, 'stop', '--topic', 'other')['activity'] == 'idle'
        assert process.poll() is None
        cli(project, 'stop')
        process.communicate(timeout=5)
        (project / 'side-effect').unlink()
        process = start(project)
        assert wait_running(project)['execution']['id'] != first
        code = '''
import sys
sys.path.insert(0, sys.argv[1])
from opc.core.topic_workspace import TopicWorkspace
from opc.core.topic_control import stop
stop(TopicWorkspace(sys.argv[2], 'research'), execution_id=sys.argv[3])
'''
        stale = subprocess.run([sys.executable, '-c', code, str(project / '.archa/runtime'),
                                str(project), first], capture_output=True, text=True)
        assert stale.returncode == 0, stale.stderr
        assert process.poll() is None
        assert cli(project, 'status')['activity'] == 'running'
        cli(project, 'stop')
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_unknown_ownership_refuses_cleanup_and_dispatch(project):
    long_executor(project)
    process = start(project)
    wait_running(project)
    process.kill()
    process.wait(timeout=5)
    description = project / '.archa/.execution.json'
    original = description.read_text()
    record = json.loads(original)
    record['id'] = 'unverifiable-owner'
    description.write_text(json.dumps(record))
    try:
        before = {p: p.read_bytes() for p in (project / '.archa/topics/research').rglob('*') if p.is_file()}
        assert cli(project, 'status')['activity'] == 'unknown'
        assert 'ownership cannot be verified' in cli(project, 'step', ok=False)
        assert {p: p.read_bytes() for p in before} == before
    finally:
        description.write_text(original)
        cli(project, 'stop')


def test_stop_snapshot_can_race_with_new_start_without_touching_it(project):
    long_executor(project)
    process = start(project)
    first = wait_running(project)['execution']['id']
    code = '''
import pathlib,sys,time
sys.path.insert(0, sys.argv[1])
from opc.core.topic_workspace import TopicWorkspace
from opc.core.topic_control import stop
original = pathlib.Path.touch
project = pathlib.Path(sys.argv[2])
def pause(path, *a, **kw):
    if path.name.startswith('.stop-'):
        (project / 'snapshot-read').write_text('ready')
        while not (project / 'release-stop').exists(): time.sleep(.01)
    return original(path, *a, **kw)
pathlib.Path.touch = pause
stop(TopicWorkspace(project, 'research'))
'''
    stopper = subprocess.Popen([sys.executable, '-c', code, str(project / '.archa/runtime'),
                                str(project)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not (project / 'snapshot-read').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (project / 'snapshot-read').exists()
        cli(project, 'stop')
        process.communicate(timeout=5)
        (project / 'side-effect').unlink()
        process = start(project)
        second = wait_running(project)['execution']['id']
        assert second != first
        (project / 'release-stop').touch()
        _, stderr = stopper.communicate(timeout=5)
        assert stopper.returncode == 0, stderr
        assert process.poll() is None
        assert cli(project, 'status')['execution']['id'] == second
        cli(project, 'stop')
        process.communicate(timeout=5)
    finally:
        for child in (stopper, process):
            if child.poll() is None:
                child.kill()
                child.wait()


def test_stop_confirms_descendant_can_no_longer_write(project):
    long_executor(project)
    config_path = project / '.archa/workers.json'
    config = json.loads(config_path.read_text())
    child = "import pathlib,time; p=pathlib.Path('heartbeat');\nwhile True:\n p.write_text(str(time.monotonic())); time.sleep(.01)"
    parent = "import subprocess,sys,pathlib,time; subprocess.Popen([sys.executable,'-c', " + repr(child) + "]); pathlib.Path('side-effect').touch(); time.sleep(30)"
    config['roles']['executor']['command'] = [sys.executable, '-c', parent]
    config_path.write_text(json.dumps(config))
    process = start(project)
    try:
        wait_running(project)
        deadline = time.monotonic() + 5
        heartbeat = project / 'heartbeat'
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert heartbeat.exists()
        assert cli(project, 'stop')['activity'] == 'idle'
        before = heartbeat.read_text()
        time.sleep(.1)
        assert heartbeat.read_text() == before
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
