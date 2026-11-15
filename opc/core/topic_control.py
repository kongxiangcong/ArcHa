"""Execution identity, cooperative stop, and exclusive crash recovery."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sys
import time
import uuid

from .platform import execution_control


def read_execution(workspace):
    try:
        return json.loads((workspace.control / '.execution.json').read_text())
    except FileNotFoundError:
        return None


def publish(workspace, record):
    path = workspace.control / '.execution.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record), encoding='utf-8')
    os.replace(temporary, path)


def identity(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                raise OSError(ctypes.get_last_error(), 'cannot read process creation time')
            if times[1].dwHighDateTime or times[1].dwLowDateTime:
                return None
            return {'pid': pid, 'start': (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}
        finally:
            kernel.CloseHandle(handle)
    if not sys.platform.startswith('linux'):
        return None
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] in {'Z', 'X'}:
            return None
        return {'pid': pid, 'start': fields[19],
                'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(owner):
    return owner is not None and identity(owner['pid']) == owner


def tree_members(record):
    """Verify the surviving session using its inherited random ownership token."""
    worker = record.get('worker')
    if worker is None:
        return []
    if worker == 'starting' or not sys.platform.startswith('linux'):
        raise ValueError('unknown execution: cannot confirm previous Worker ownership')
    if worker['boot'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        return []
    members = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[3]) != worker['pid'] or fields[0] in {'Z', 'X'}:
                continue
            env = (entry / 'environ').read_bytes().split(b'\0')
            if ('ARCHA_EXECUTION=' + record['id']).encode() not in env:
                raise ValueError('unknown execution: surviving process ownership cannot be verified')
            members.append({'pid': int(entry.name), 'start': fields[19],
                            'boot': worker['boot']})
        except (FileNotFoundError, ProcessLookupError):
            continue
    return members


def end_previous(workspace, record):
    if not record:
        return
    # Only the exclusive lock holder may recover an abandoned execution.
    members = tree_members(record)
    if members:
        # Verify individual birth identities and use pidfds: a recycled PID is
        # never signalled between inspecting /proc and sending the signal.
        for owner in members:
            pid = owner['pid']
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                if identity(pid) == owner:
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
            finally:
                os.close(fd)
        deadline = time.monotonic() + 3
        while tree_members(record):
            if time.monotonic() > deadline:
                raise ValueError('unknown execution: cannot confirm previous process tree ended')
            time.sleep(.01)
    from .workspace import TopicWorkspace
    TopicWorkspace(workspace.project, record['topic']).recover()
    (workspace.control / ('.stop-' + record['id'])).unlink(missing_ok=True)
    (workspace.control / '.execution.json').unlink(missing_ok=True)


def activity(workspace):
    record = read_execution(workspace)
    if not record or record['topic'] != workspace.topic:
        return {'activity': 'idle', 'execution': None}
    state = 'running' if alive(record.get('controller')) else 'unknown'
    if state == 'running' and (workspace.control / ('.stop-' + record['id'])).exists():
        state = 'stopping'
    return {'activity': state, 'execution': record}


def check_stop(workspace):
    record = read_execution(workspace)
    if record and (workspace.control / ('.stop-' + record['id'])).exists():
        raise ValueError('execution interrupted: stop requested')


@contextmanager
def lifecycle(workspace):
    with workspace.writer():
        previous = read_execution(workspace)
        end_previous(workspace, previous)
        if not previous or previous['topic'] != workspace.topic:
            workspace.recover()
        status = workspace.status()
        record = {'id': uuid.uuid4().hex, 'topic': workspace.topic,
                  'controller': identity(os.getpid()), 'worker': None,
                  'role': status['next_action'], 'round': status['current_round'],
                  'started_at': datetime.now(timezone.utc).isoformat()}
        stop = workspace.control / ('.stop-' + record['id'])
        publish(workspace, record)
        def check():
            return 'stop requested' if stop.exists() else None
        def register(process, state):
            if state == 'ended':
                record['worker'] = None
            elif state == 'starting':
                current = workspace.status()
                record.update(worker='starting', role=current['next_action'],
                              round=current['current_round'],
                              started_at=datetime.now(timezone.utc).isoformat())
            elif getattr(process, 'pid', None):
                owner = identity(process.pid)
                if owner:
                    record['worker'] = owner
            publish(workspace, record)
        error_path = workspace.path / '.last-error'
        error_path.unlink(missing_ok=True)
        try:
            try:
                with execution_control(check, recorder=register,
                                       env={'ARCHA_EXECUTION': record['id']}):
                    yield
            finally:
                # Only the lifecycle owner cleans the execution after tree exit.
                end_previous(workspace, record)
        except Exception as exc:
            error_path.write_text(str(exc), encoding='utf-8')
            raise


def stop(workspace, timeout=10, *, execution_id=None):
    record = read_execution(workspace)
    if not record or record['topic'] != workspace.topic or (execution_id and execution_id != record['id']):
        return {**workspace.status(), **activity(workspace)}
    request = workspace.control / ('.stop-' + record['id'])
    request.touch(exist_ok=True)
    deadline = time.monotonic() + timeout
    confirmed = False
    try:
        while True:
            current = read_execution(workspace)
            if current and current['id'] != record['id']:
                confirmed = True
                return {**workspace.status(), **activity(workspace)}
            try:
                with workspace.writer():
                    current = read_execution(workspace)
                    if current and current['id'] == record['id']:
                        end_previous(workspace, current)
                    confirmed = True
                    return {**workspace.status(), **activity(workspace)}
            except ValueError as exc:
                if 'lock is held' not in str(exc):
                    raise
            if time.monotonic() >= deadline:
                raise ValueError('stop requested; execution end is not yet confirmed')
            time.sleep(.02)
    finally:
        if confirmed:
            request.unlink(missing_ok=True)
