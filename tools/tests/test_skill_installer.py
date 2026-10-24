"""Exercise the installer with Windows short-name temporary directories."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows 8.3 path aliases")
def test_installer_accepts_short_temp_path(tmp_path):
    folder = tmp_path / "temporary-directory-with-long-name"
    folder.mkdir()
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(folder), buffer, len(buffer))
    if not length:
        raise ctypes.WinError()
    short = buffer.value
    if short.casefold() == str(folder).casefold():
        pytest.skip("This filesystem does not provide an 8.3 alias")

    destination = tmp_path / "installed/skills"
    installer = Path(__file__).resolve().parents[1] / "install_research_skills.py"
    result = subprocess.run(
        [sys.executable, "-B", str(installer), "--destination", str(destination)],
        env={**os.environ, "TEMP": short, "TMP": short}, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert (destination / "archa-map/assets/runtime/manifest.json").is_file()
    assert (destination / "archa-task/SKILL.md").is_file()
    assert (destination / "archa-loop/SKILL.md").is_file()
