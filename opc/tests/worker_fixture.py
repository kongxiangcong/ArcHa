"""Deterministic file-protocol CLI used only by tests."""
from pathlib import Path
import sys


def custom():
    return {'provider': 'custom', 'command': [sys.executable, str(Path(__file__).resolve()),
            '{topic_dir}', '{state_file}', '{output_file}']}


if __name__ == '__main__':
    topic, state, output = map(Path, sys.argv[1:])
    prompt = sys.stdin.read()
    role = prompt.splitlines()[0].removeprefix('Role: ')
    if role.startswith('expert'):
        state.write_text((topic / 'STATE.md').read_text() + '\nPrepared one focused evidence question.\n')
        if role != 'expert_finalize':
            output.write_text('# Probe\n\nCheck the supplied evidence for:\n' + (topic / 'GOAL.md').read_text())
    else:
        output.write_text('# Result\n\nObserved the current probe:\n' + (output.parent / 'probe.md').read_text())
    print('Deterministic ' + role + ' completed.')
