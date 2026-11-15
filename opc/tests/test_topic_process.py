"""Real process lifecycle fault boundary agreed in the topic specification."""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from opc.core.platform import Process, execution_control, ExecutionControl


def test_registration_failure_reaps_started_descendants(tmp_path, monkeypatch):
    marker = tmp_path / 'late-write'
    ready = tmp_path / 'ready'
    child = f"import time; from pathlib import Path; Path({str(ready)!r}).touch(); time.sleep(1); Path({str(marker)!r}).touch()"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
    def fail_record(self, process, state):
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        raise OSError('registration failed')
    monkeypatch.setattr(ExecutionControl, 'record', fail_record)
    with execution_control(lambda: None, tmp_path):
        with pytest.raises(OSError, match='registration failed'):
            Process([sys.executable, '-c', parent])
    time.sleep(1.2)
    assert not marker.exists()
