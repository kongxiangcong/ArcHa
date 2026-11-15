"""Initial deterministic topic Worker; command lifecycle expands in ticket 02."""
import json


def invoke(workspace, role, prompt, state_file, output_file, log_file):
    config = json.loads((workspace.control / 'workers.json').read_text())
    spec = config['roles'][role]
    if spec != {'preset': 'scripted'}:
        raise ValueError('unsupported Worker configuration for roles.' + role + '; this version supports only preset scripted')
    if role == 'expert':
        state_file.write_text((workspace.path / 'STATE.md').read_text() + '\nPrepared one focused evidence question.\n')
        output_file.write_text('# Probe\n\nCheck the supplied evidence for:\n' + (workspace.path / 'GOAL.md').read_text())
    else:
        output_file.write_text('# Result\n\nObserved the current probe:\n' + (workspace.path / 'steps' / output_file.parent.name / 'probe.md').read_text())
    log_file.write_text('Deterministic ' + role + ' completed.\n')
