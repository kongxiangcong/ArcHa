"""Reading projections through the existing Observer HTTP boundary."""
from fastapi.testclient import TestClient
from opc.core.workspace import TopicWorkspace
from opc.observer.api import create_app


def test_original_excerpts_and_missing_results(tmp_path):
    workspace = TopicWorkspace(tmp_path, 'reading')
    workspace.initialize('Original goal', 3)
    (workspace.path / 'GOAL.md').write_text('# Topic\n\nPreamble\n\n## Objective\n' + '界' * 241 + '\n## Other\nIgnore this')
    state = workspace.path / 'STATE.md'
    state.write_text(state.read_text() + '\n## Observations\n\nA   measured fact.\n\n## Empty\n')
    step = workspace.path / 'steps/step-01'
    step.mkdir()
    (step / 'probe.md').write_text('# ' + '题' * 121 + '\n\n- literal evidence\n```py\nprint(1)\n```')
    with TestClient(create_app(tmp_path)) as client:
        detail = client.get('/api/observer/v1/topics/reading').json()
        goal = next(m for m in detail['materials'] if m['name'] == 'GOAL.md')['excerpt']
        assert goal['text'] == '界' * 240 + '…'
        assert goal['truncated'] is True
        sections = next(m for m in detail['materials'] if m['name'] == 'STATE.md')['sections']
        assert next(s for s in sections if s['title'] == 'Observations')['text'] == 'A measured fact.'
        assert next(s for s in sections if s['title'] == 'Empty')['empty'] is True
        probe = detail['rounds'][0]['materials'][0]['excerpt']
        assert probe['title'] == '题' * 120 + '…'
        assert probe['title_truncated'] is True
        assert '- literal evidence' in probe['text']
        assert detail['rounds'][0]['completed'] is False
        (step / 'result.md').write_text('# Result\n')
        detail = client.get('/api/observer/v1/topics/reading').json()
        result = next(m for m in detail['rounds'][0]['materials'] if m['name'] == 'result.md')
        assert result['excerpt']['empty'] is True
