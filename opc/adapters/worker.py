"""File-protocol Workers with direct process logs and owned process lifetimes."""
import os
import subprocess

from ..core.platform import Process
from .providers import ProviderRequest, configuration, launch


def invoke(workspace, role, prompt, state_file, output_file, log_file):
    spec = configuration(workspace)['expert' if role.startswith('expert') else role]
    if output_file != state_file:
        output_file.unlink(missing_ok=True)
    prompt_file = log_file.with_suffix('.prompt.md')
    prompt_file.write_text(prompt, encoding='utf-8')
    command = None
    try:
        command = launch(ProviderRequest(role, workspace.project, workspace.path, prompt_file,
                                         state_file, output_file, spec))
        with log_file.open('wb') as log, prompt_file.open('rb') as source:
            with Process(command.argv, cwd=command.cwd, env={**os.environ, **command.env},
                         stdin=source, stdout=log, stderr=log) as process:
                try:
                    code = process.wait(timeout=spec['timeout_seconds'])
                except subprocess.TimeoutExpired as exc:
                    raise ValueError(role + ': Worker timed out; see ' + str(log_file)) from exc
                finally:
                    process.kill_tree()
                if process.cancel_reason:
                    raise ValueError(role + ': Worker interrupted: ' + process.cancel_reason)
                if code:
                    raise ValueError(f'{role}: Worker exited with code {code}; see {log_file}')
        required = state_file if role.startswith('expert') else output_file
        if not required.is_file() or not required.read_text(encoding='utf-8').strip():
            raise ValueError(role + ': missing or blank required output: ' + str(required))
    finally:
        if command is not None:
            for path in command.cleanup_paths:
                path.unlink(missing_ok=True)
        prompt_file.unlink(missing_ok=True)
