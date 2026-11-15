"""Stateless argv Workers with streamed diagnostics and owned process lifetimes."""
import json
import math
import os
from pathlib import Path
import string
import subprocess
import threading

from ..core.platform import Process

PRESETS = {
    'codex': {'command': ['codex', 'exec', '--ephemeral', '--skip-git-repo-check', '-C', '{workdir}',
                          '-s', 'workspace-write', '-o', '{output_file}', '-'],
              'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 1800},
    'scripted': {},
}
FIELDS = {'command', 'preset', 'input_mode', 'output_mode', 'timeout_seconds',
          'env', 'model', 'reasoning_effort'}
VARIABLES = {'workdir', 'topic_dir', 'prompt_file', 'output_file', 'state_file',
             'model', 'reasoning_effort'}


def configuration(workspace):
    path = workspace.control / 'workers.json'
    if not path.exists():
        path = Path(__file__).parents[1] / 'scaffold/topic_workers.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or set(config) != {'roles'}:
        raise ValueError('workers.json must contain only roles')
    roles = config['roles']
    if not isinstance(roles, dict) or set(roles) != {'expert', 'executor'}:
        raise ValueError('roles must contain expert and executor')
    result = {}
    for role, raw in roles.items():
        if not isinstance(raw, dict) or set(raw) - FIELDS:
            raise ValueError(role + ': unknown fields or invalid role object')
        if ('preset' in raw) == ('command' in raw):
            raise ValueError(role + ': supply exactly one command or preset')
        preset = raw.get('preset')
        if preset is not None and (not isinstance(preset, str) or preset not in PRESETS):
            raise ValueError(role + ': unknown preset')
        if preset == 'scripted':
            if raw != {'preset': 'scripted'}:
                raise ValueError(role + ': scripted preset takes no options')
            result[role] = raw
            continue
        spec = {**PRESETS[preset], 'command': list(PRESETS[preset]['command'])} if preset else {}
        spec.update(raw)
        command = spec.get('command')
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x.strip() for x in command):
            raise ValueError(role + ': command must be a nonempty string argv array')
        if spec.get('input_mode') not in ('stdin', 'file'):
            raise ValueError(role + ': invalid input_mode')
        if spec.get('output_mode') not in (('file',) if role == 'expert' else ('file', 'stdout')):
            raise ValueError(role + ': invalid output_mode')
        timeout = spec.get('timeout_seconds')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(role + ': timeout_seconds must be positive')
        env = spec.get('env', {})
        if not isinstance(env, dict) or not all(isinstance(k, str) and k and '=' not in k and '\0' not in k and isinstance(v, str) and '\0' not in v for k, v in env.items()):
            raise ValueError(role + ': env must map strings to strings')
        for name in ('model', 'reasoning_effort'):
            if name in spec and (not isinstance(spec[name], str) or not spec[name].strip()):
                raise ValueError(role + ': ' + name + ' must be a nonempty string')
        if preset == 'codex':
            if 'model' in spec:
                command.extend(['--model', '{model}'])
            if 'reasoning_effort' in spec:
                command.extend(['-c', 'model_reasoning_effort=\"{reasoning_effort}\"'])
        for argument in command:
            for _, field, format_spec, conversion in string.Formatter().parse(argument):
                if field is not None and (field not in VARIABLES or format_spec or conversion or (field in {'model', 'reasoning_effort'} and field not in spec)):
                    raise ValueError(role + ': unavailable template variable: ' + field)
        result[role] = spec
    return result


def invoke(workspace, role, prompt, state_file, output_file, log_file):
    spec = configuration(workspace)['expert' if role == 'expert_finalize' else role]
    if spec.get('preset') == 'scripted':
        if role.startswith('expert'):
            state_file.write_text((workspace.path / 'STATE.md').read_text() + '\nPrepared one focused evidence question.\n')
            if role != 'expert_finalize':
                output_file.write_text('# Probe\n\nCheck the supplied evidence for:\n' + (workspace.path / 'GOAL.md').read_text())
        else:
            output_file.write_text('# Result\n\nObserved the current probe:\n' + (output_file.parent / 'probe.md').read_text())
        log_file.write_text('Deterministic ' + role + ' completed.\n')
        return
    if output_file != state_file:
        output_file.unlink(missing_ok=True)
    prompt_file = log_file.with_suffix('.prompt.md')
    prompt_file.write_text(prompt, encoding='utf-8')
    values = dict(workdir=str(workspace.project), topic_dir=str(workspace.path),
                  prompt_file=str(prompt_file), state_file=str(state_file), output_file=str(output_file))
    values.update({k: spec[k] for k in ('model', 'reasoning_effort') if k in spec})
    argv = [arg.format_map(values) for arg in spec['command']]
    captured = []
    errors = []
    lock = threading.Lock()
    try:
        with log_file.open('wb') as log, prompt_file.open('rb') as source:
            def stream(pipe, capture):
                try:
                    while chunk := pipe.read1(65536):
                        if capture:
                            captured.append(chunk)
                        with lock:
                            log.write(chunk)
                            log.flush()
                except BaseException as exc:
                    errors.append(exc)
            threads = []
            try:
                with Process(argv, cwd=workspace.project, env={**os.environ, **spec.get('env', {})},
                             stdin=source if spec['input_mode'] == 'stdin' else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                    for pipe, capture in ((process.stdout, True), (process.stderr, False)):
                        thread = threading.Thread(target=stream, args=(pipe, capture))
                        thread.start()
                        threads.append(thread)
                    try:
                        code = process.wait(timeout=spec['timeout_seconds'])
                    except subprocess.TimeoutExpired as exc:
                        raise ValueError(role + ': Worker timed out') from exc
                    finally:
                        process.kill_tree()
                        for thread in threads:
                            thread.join()
                    if process.cancel_reason:
                        raise ValueError(role + ': Worker interrupted: ' + process.cancel_reason)
                    if code:
                        raise ValueError(f'{role}: Worker exited with code {code}; see {log_file}')
            finally:
                for thread in threads:
                    thread.join()
            if errors:
                raise OSError('Worker log streaming failed') from errors[0]
        if spec['output_mode'] == 'stdout':
            output_file.write_bytes(b''.join(captured))
        required = state_file if role.startswith('expert') else output_file
        if not required.is_file() or not required.read_text(encoding='utf-8').strip():
            raise ValueError(role + ': missing or blank required output: ' + str(required))
    finally:
        prompt_file.unlink(missing_ok=True)
