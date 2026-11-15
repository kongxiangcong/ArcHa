"""Exercise the installer with Windows short-name temporary directories."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.tests.test_topic_skills import ROOT, call


def test_install_retires_old_skills_and_preserves_unrelated_skills(tmp_path):
    destination = tmp_path / 'skills'
    retired = ('archa-map', 'archa-task', 'archa-loop', 'archa-log')
    for name in (*retired, 'unrelated'):
        folder = destination / name
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text(name)
    result = call(ROOT / 'tools/install_research_skills.py', '--destination', destination)
    assert {p.name for p in destination.iterdir()} == {'archa-discuss', 'archa-run', 'unrelated'}
    assert (destination / 'unrelated/SKILL.md').read_text() == 'unrelated'
    assert {Path(p).name for p in result['backups']} == set(retired)
    for backup in map(Path, result['backups']):
        assert (backup / 'SKILL.md').read_text() == backup.name
    result = call(ROOT / 'tools/install_research_skills.py', '--destination', destination)
    assert {Path(p).name for p in result['backups']} == {'archa-discuss', 'archa-run'}


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
    assert (destination / "archa-discuss/assets/runtime/manifest.json").is_file()
    assert (destination / "archa-run/SKILL.md").is_file()
