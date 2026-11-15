"""Project layout helper uses the same local topic entry as skills."""
import json
from tools.tests.test_topic_skills import ROOT, call


def test_plan_is_read_only_and_apply_preserves_existing_topic(tmp_path):
    helper = ROOT / 'tools/project_layout.py'
    args = ['--project-root', tmp_path, '--topic', 'example']
    plan = call(helper, 'paths', *args)
    assert plan['state'] == str(tmp_path / '.archa/topics/example/STATE.md')
    assert not list(tmp_path.iterdir())
    call(ROOT / 'skills/archa-discuss/scripts/initialize.py', '--project', tmp_path)
    call(helper, 'init', *args, '--goal', 'Original goal', '--apply')
    goal = tmp_path / '.archa/topics/example/GOAL.md'
    original = goal.read_bytes()
    call(helper, 'init', *args, '--goal', 'Replacement', '--apply')
    assert goal.read_bytes() == original
