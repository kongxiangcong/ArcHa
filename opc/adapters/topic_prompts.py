"""Minimal stateless role context; historical materials are available by path."""
def prompt(workspace, role, directory, state_file, output_file):
    text = (f'Role: {role}\nHistory: {workspace.path / "steps"}\n'
            f'Write complete output to {output_file}. Write complete state to {state_file}.\n'
            'Do not edit authoritative documents, budget, or completed rounds.\n'
            f'\nGOAL\n{(workspace.path / "GOAL.md").read_text()}\n'
            f'STATE\n{(workspace.path / "STATE.md").read_text()}\n')
    if role == 'expert':
        text += 'Absorb the last result; update facts, explanations, conditional closed branches and questions. Choose one question and write its probe, or mark COMPLETED/BLOCKED.\n'
        previous = workspace.path / 'steps' / f'step-{int(directory.name[5:]) - 1:02d}'
        if previous.exists():
            for name in ('probe.md', 'result.md'):
                text += f'\nPREVIOUS {name}\n{(previous / name).read_text()}\n'
    else:
        text += 'Execute the current probe. Record actions, observations, answer and original evidence locations. Verify interventions actually took effect.\n'
        text += '\nPROBE\n' + (directory / 'probe.md').read_text()
    return text
