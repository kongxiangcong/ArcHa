"""Runtime integrity, upgrades and relocated skill installation."""
import importlib.util
from pathlib import Path
import shutil
import pytest
from tools.tests.test_topic_skills import ROOT, call

spec = importlib.util.spec_from_file_location('initialize', ROOT / 'skills/archa-discuss/scripts/initialize.py')
initialize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(initialize)


def test_bundle_is_relocatable_and_integrity_checked(tmp_path):
    skills = tmp_path / 'skills'
    call(ROOT / 'tools/install_research_skills.py', '--destination', skills)
    moved = tmp_path / 'relocated'
    shutil.move(skills / 'archa-discuss', moved)
    target = tmp_path / 'target'
    target.mkdir()
    call(moved / 'scripts/initialize.py', '--project', target, cwd=target)
    entry = target / '.archa/archa.py'
    assert call(entry, 'init', '-p', target, '--topic', 'portable', '--goal', 'Inspect')['status'] == 'IN_PROGRESS'
    runtime = target / '.archa/runtime'
    manifest = initialize.verify(runtime)
    assert 'opc/log.py' in manifest['files']
    assert 'opc/core/ledger.py' not in manifest['files']
    (runtime / 'opc/cli.py').write_text('# tampered')
    with pytest.raises(ValueError, match='modified'):
        initialize.verify(runtime)


def test_explicit_upgrade_preserves_topic_and_previous_runtime(tmp_path):
    runtime = tmp_path / 'bundle'
    initialize.snapshot(ROOT, runtime)
    project = tmp_path / 'project'
    project.mkdir()
    initialize.initialize(project, runtime)
    entry = project / '.archa/archa.py'
    call(entry, 'init', '-p', project, '--topic', 'retained', '--goal', 'Original')
    state = project / '.archa/topics/retained/STATE.md'
    before = state.read_bytes()
    import json
    file = runtime / 'opc/cli.py'
    file.write_text(file.read_text() + '\n# new release\n')
    manifest = json.loads((runtime / 'manifest.json').read_text())
    manifest['files']['opc/cli.py'] = initialize.digest(file)
    manifest['snapshot_sha256'] = 'updated'
    (runtime / 'manifest.json').write_text(json.dumps(manifest))
    result = initialize.initialize(project, runtime, update=True)
    assert Path(result['runtime_backup']).is_dir()
    assert state.read_bytes() == before
    assert call(entry, 'status', '-p', project, '--topic', 'retained')['completed_rounds'] == 0
