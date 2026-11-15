"""Real process lifecycle fault boundary agreed in the topic specification."""
import sys
import time

import pytest

from opc.core.platform import Process, execution_control


def test_registration_failure_reaps_started_descendants(tmp_path):
    marker = tmp_path / 'late-write'
    ready = tmp_path / 'ready'
    child = f"import time; from pathlib import Path; Path({str(ready)!r}).touch(); time.sleep(1); Path({str(marker)!r}).touch()"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
    recorded = []
    def fail_record(process, state):
        recorded.append(state)
        if state != "running":
            return
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists(), 'descendant must start before registration fails'
        raise OSError('registration failed')
    with execution_control(lambda: None, recorder=fail_record):
        with pytest.raises(OSError, match='registration failed'):
            Process([sys.executable, '-c', parent])
    assert recorded == ["starting", "running", "ended"]
    time.sleep(1.2)
    assert not marker.exists()
