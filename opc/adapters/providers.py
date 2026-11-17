"""Validated provider configuration and stateless process launch descriptions."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import string
import sys

# DSH patches replace config objects. Intercept the resolved config so local
# provider/effort and native !!js expressions survive the model override.
DSH_MODEL_OVERRIDE = """export default function override(ctx, config) {
  ctx.on('internal/config', (fiber, next) => {
    const value = next();
    return fiber.entry?.options.id === 'agent-default-model'
      ? { ...value, model: config.model } : value;
  });
  ctx.provide('archaModelOverride', {});
}
"""

MIGRATION = 'See opc/README.md#worker-configuration-migration for manual migration.'
COMMON = {'provider', 'model', 'timeout_seconds', 'env'}
VARIABLES = {'workdir', 'topic_dir', 'prompt_file', 'output_file', 'state_file', 'model'}


@dataclass(frozen=True)
class ProviderRequest:
    role: str
    project: Path
    topic: Path
    prompt_file: Path
    state_file: Path
    output_file: Path
    config: dict


@dataclass(frozen=True)
class Launch:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    cleanup_paths: tuple[Path, ...] = ()


def configuration(workspace):
    path = workspace.control / 'workers.json'
    if not path.exists():
        path = Path(__file__).parents[1] / 'scaffold/workers.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or set(config) != {'expert', 'executor'}:
        raise ValueError('workers.json must contain expert and executor directly. ' + MIGRATION)
    result = {}
    for role, raw in config.items():
        if not isinstance(raw, dict):
            raise ValueError(role + ': invalid role object')
        if {'preset', 'input_mode', 'output_mode'} & raw.keys():
            raise ValueError(role + ': obsolete preset/input_mode/output_mode. ' + MIGRATION)
        provider = raw.get('provider')
        if provider not in ('codex', 'dsh', 'custom'):
            raise ValueError(role + ': unknown provider; expected codex, dsh or custom')
        allowed = COMMON | {'codex': {'reasoning_effort'}, 'dsh': set(), 'custom': {'command'}}[provider]
        if raw.keys() - allowed:
            raise ValueError(role + ': unknown fields or unsupported provider options: ' + ', '.join(sorted(raw.keys() - allowed)))
        spec = {'timeout_seconds': 1800, 'model': '', 'env': {}, **raw}
        timeout = spec['timeout_seconds']
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(role + ': timeout_seconds must be positive and finite')
        env = spec['env']
        if not isinstance(env, dict) or not all(isinstance(k, str) and k and '=' not in k and '\0' not in k and isinstance(v, str) and '\0' not in v for k, v in env.items()):
            raise ValueError(role + ': env must map strings to strings')
        if not isinstance(spec['model'], str) or '\0' in spec['model'] or (spec['model'] and not spec['model'].strip()):
            raise ValueError(role + ': model must be a string, empty to use CLI defaults')
        if 'reasoning_effort' in spec and (not isinstance(spec['reasoning_effort'], str) or not spec['reasoning_effort'].strip() or '\0' in spec['reasoning_effort']):
            raise ValueError(role + ': reasoning_effort must be a nonempty string')
        if provider == 'custom':
            command = spec.get('command')
            if not isinstance(command, list) or not command or not all(isinstance(x, str) and x.strip() and '\0' not in x for x in command):
                raise ValueError(role + ': command must be a nonempty string argv array')
            for argument in command:
                for _, field, format_spec, conversion in string.Formatter().parse(argument):
                    if field is not None and (field not in VARIABLES or format_spec or conversion or (field == 'model' and not spec['model'])):
                        raise ValueError(role + ': unavailable template variable: ' + field)
        result[role] = spec
    return result


def launch(request):
    spec = request.config
    cleanup_paths = ()
    if spec['provider'] == 'codex':
        argv = ['codex', 'exec', '--ephemeral', '--json', '--skip-git-repo-check', '-C', str(request.project)]
        if spec['model']:
            argv.extend(['--model', spec['model']])
        if 'reasoning_effort' in spec:
            argv.extend(['-c', 'model_reasoning_effort=' + json.dumps(spec['reasoning_effort'])])
        argv.append('-')
    elif spec['provider'] == 'dsh':
        argv = ['dsh', '--profile', 'headless']
        if spec['model']:
            patch = request.prompt_file.with_suffix('.provider.yml')
            plugin = patch.with_suffix('.mjs')
            try:
                plugin.write_text(DSH_MODEL_OVERRIDE, encoding='utf-8')
                patch.write_text('- insert:\n    - id: archa-model-override\n      name: '
                                 + json.dumps(plugin.as_uri()) + '\n      config:\n        model: '
                                 + json.dumps(spec['model'])
                                 + '\n- id: agent-default-model\n  inject: [archaModelOverride]\n', encoding='utf-8')
            except OSError:
                for temporary in (patch, plugin):
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError as cleanup_error:
                        print(f'Could not remove {temporary}: {cleanup_error}', file=sys.stderr)
                raise
            cleanup_paths = (patch, plugin)
            argv.extend(['--patch', str(patch)])
        argv.extend(['--json', '-'])
    else:
        values = dict(workdir=str(request.project), topic_dir=str(request.topic),
                      prompt_file=str(request.prompt_file), state_file=str(request.state_file),
                      output_file=str(request.output_file), model=spec['model'])
        argv = [arg.format_map(values) for arg in spec['command']]
    return Launch(argv, request.project, spec['env'], cleanup_paths)
