"""On-demand, offline reading report from authoritative topic materials."""
from pathlib import Path
import re
from .core.workspace import TopicWorkspace


def excerpt_text(text):
    lines = text.splitlines()
    prose = ' '.join(line.strip() for line in lines if line.strip() and
                     not line.startswith(('#', 'STATUS:', 'MAX_ROUNDS:')))
    # Bounded quotations keep the report a reading guide, not a second state file.
    # Links in quoted excerpts remain in their original document's context.
    prose = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', prose)
    return '> ' + (prose[:600] + '…' if len(prose) > 600 else prose)


def excerpt(path):
    return excerpt_text(path.read_text(encoding='utf-8'))


def understanding(path):
    # Preserve each cognitive category, including later unresolved questions.
    sections = re.split(r'(?m)^## ', path.read_text(encoding='utf-8'))
    if len(sections) == 1:
        return excerpt_text(sections[0])
    return '\n\n'.join('### ' + section.split('\n', 1)[0] + '\n\n' +
                        excerpt_text(section.partition('\n')[2]) for section in sections[1:])


def generate_report(project: Path, topic: str) -> Path:
    workspace = TopicWorkspace(project, topic)
    with workspace.writer():
        status = workspace.status()
        if status['publishing']:
            raise ValueError('topic publication is pending; resume before generating a report')
        parts = [f'# Research progress: {topic}',
                 'Derived reading report. GOAL.md, STATE.md and committed rounds remain authoritative. '
                 'The current understanding below is not a historical state snapshot.',
                 f"The topic is **{status['status']}**, with {status['completed_rounds']} completed "
                 f"rounds out of {status['max_rounds']}. Next action: {status['next_action']}.",
                 '## Research objective\n\n[Source: GOAL.md](GOAL.md)\n\n' +
                 excerpt(workspace.path / 'GOAL.md'),
                 '## Current understanding and remaining questions\n\n[Source: STATE.md](STATE.md)\n\n' +
                 understanding(workspace.path / 'STATE.md')]
        for number, complete in workspace.rounds():
            relative = f'steps/step-{number:02d}'
            parts.append(f'## Round {number}: ' + ('observed evidence' if complete else 'pending investigation'))
            for name in ('probe.md', 'result.md') if complete else ('probe.md',):
                path = workspace.path / relative / name
                parts.append(f'[{name}]({relative}/{name})\n\n' + excerpt(path))
        parts.append('## Interpretation\n\nRead the observations above against the current understanding and '
                     'its stated conditions. Pending probes have no result yet. Original materials and scripts '
                     'remain at their cited locations; this report does not establish additional findings.')
        output = workspace.path / 'PROGRESS_LOG.md'
        if output.is_symlink():
            raise ValueError('report path must not be redirected')
        output.write_text('\n\n'.join(parts) + '\n', encoding='utf-8')
        return output
