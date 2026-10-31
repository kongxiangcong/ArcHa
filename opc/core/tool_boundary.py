"""The task tool boundary; model transports remain outside confined subprocesses.

Codex consumes the same read/write grants as a native permissions profile. DSH
runs filesystem work through the confined command entry point below. Missing
new files matched only by a glob never grant their entire parent directory.
"""
from __future__ import annotations

import ctypes as C
import errno
import json
import os
from pathlib import Path
import sys

RUNTIME_READ = ['/usr', '/bin', '/sbin', '/lib', '/lib64', '/etc/ld.so.cache',
                '/etc/localtime', '/etc/nsswitch.conf', '/etc/passwd', '/etc/group',
                '/proc/cpuinfo', '/proc/meminfo', '/sys/devices/system/cpu',
                '/dev/urandom', '/dev/random']


def tool_policy(tree: Path, *, editable=(), scratch=(), protected=(), reads=()) -> dict:
    from .config import denied
    tree = tree.resolve()
    protected = list(protected) + ['.git', '.git/**']
    writes = []
    limitations = []
    def contained(target):
        resolved = target.resolve()
        if not resolved.is_relative_to(tree):
            raise ValueError('tool write path escapes task workspace: ' + str(target))
        return resolved
    def overlaps_protected(directory):
        for pattern in protected:
            prefix = pattern
            for marker in '*?[':
                prefix = prefix.split(marker, 1)[0]
            prefix = prefix.rstrip('/').casefold()
            name = directory.casefold()
            if not prefix or prefix == name or prefix.startswith(name + '/') or name.startswith(prefix + '/'):
                return True
        return False
    for pattern in [*editable, *scratch]:
        # Only a whole subtree grants creation inside that directory. Arbitrary
        # filename globs authorize existing matching files, never their parent.
        subtree = pattern[:-3].rstrip('/') if pattern.endswith('/**') else pattern.rstrip('/') if pattern.endswith('/') else None
        literal = subtree if subtree is not None else pattern
        if not any(c in literal for c in '*?['):
            target = tree / literal
            contained(target)
            if denied(literal, protected):
                continue
            if subtree is not None:
                # A protected descendant prevents granting its enclosing tree.
                overlaps = overlaps_protected(literal)
                if overlaps:
                    limitations.append('cannot grant subtree overlapping protected paths: ' + pattern)
                    continue
                target.mkdir(parents=True, exist_ok=True)
                writes.append(str(contained(target)))
            elif target.is_file() and not target.is_symlink():
                writes.append(str(contained(target)))
            else:
                limitations.append('new file requires an existing editable subtree: ' + pattern)
            continue
        for target in tree.glob(pattern):
            contained(target)
            rel = target.relative_to(tree).as_posix()
            if target.is_file() and not target.is_symlink() and not denied(rel, protected):
                writes.append(str(contained(target)))
        limitations.append('new glob matches need an editable subtree: ' + pattern)
    return {'read': [str(tree), *[str(Path(p).resolve()) for p in reads]],
            'write': list(dict.fromkeys(writes)), 'network': False,
            'limitations': limitations}


def restrict(reads, writes, runtime=()):
    """Apply the existing benchmark Landlock/seccomp boundary to this process."""
    if sys.platform != 'linux' or os.uname().machine != 'x86_64':
        raise RuntimeError('Linux x86_64 Landlock ABI >= 3 required; refusing unisolated execution')
    libc = C.CDLL(None, use_errno=True)
    if libc.syscall(444, 0, 0, 1) < 3:
        raise RuntimeError('Landlock ABI >= 3 required; refusing unisolated execution')
    all_fs = (1 << 15) - 1
    read = (1 << 0) | (1 << 2) | (1 << 3)
    class Ruleset(C.Structure):
        _fields_ = [('fs', C.c_uint64)]
    class PathRule(C.Structure):
        _pack_ = 1
        _fields_ = [('access', C.c_uint64), ('parent', C.c_int)]
    def check(value):
        if value < 0:
            raise OSError(C.get_errno(), os.strerror(C.get_errno()))
        return value
    attr = Ruleset(all_fs)
    fd = check(libc.syscall(444, C.byref(attr), C.sizeof(attr), 0))
    def allow(path, access):
        path = Path(path)
        if not path.exists():
            return
        if not path.is_dir():
            access &= (1 << 0) | (1 << 1) | (1 << 2) | (1 << 14)
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = PathRule(access, parent)
            check(libc.syscall(445, fd, 1, C.byref(rule), 0))
        finally:
            os.close(parent)
    try:
        for path in [*RUNTIME_READ, *runtime, *reads]:
            allow(path, read)
        allow('/dev/null', read | (1 << 1))
        for path in writes:
            allow(path, all_fs)
        check(libc.prctl(38, 1, 0, 0, 0))
        check(libc.syscall(446, fd, 0))
    finally:
        os.close(fd)
    class Filter(C.Structure):
        _fields_ = [('code', C.c_ushort), ('jt', C.c_ubyte), ('jf', C.c_ubyte), ('k', C.c_uint)]
    class Program(C.Structure):
        _fields_ = [('length', C.c_ushort), ('filters', C.POINTER(Filter))]
    rules = (Filter * 8)(Filter(0x20, 0, 0, 4), Filter(0x15, 1, 0, 0xc000003e),
        Filter(0x06, 0, 0, 0x80000000), Filter(0x20, 0, 0, 0),
        Filter(0x35, 1, 0, 0x40000000), Filter(0x15, 0, 1, 41),
        Filter(0x06, 0, 0, 0x00050000 | errno.EPERM), Filter(0x06, 0, 0, 0x7fff0000))
    check(libc.prctl(22, 2, C.byref(Program(len(rules), rules)), 0, 0))


def runner_argv(policy: Path, command: list[str]) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), str(policy.resolve()), '--', *command]


def main():
    # DSH prepends its bwrap-compatible profile before the final command. The
    # frozen ArcHa grants below are stricter and replace those broad defaults.
    policy = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    command = sys.argv[sys.argv.index('--') + 1:]
    if not command:
        raise ValueError('missing tool command')
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
           'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
           'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
    env.update(policy.get('env', {}))
    restrict(policy['read'], policy['write'])
    os.execvpe(command[0], command, env)


def worker_policy(role: str, tree: Path, log_dir: Path, ctx: dict | None = None) -> dict:
    """Resolve only this invocation's fixed workspace and authorized evidence."""
    ctx = ctx or {}
    comp = ctx.get('component') or {}
    reads = ([ctx['source_root']] if ctx.get('source_root') else [])
    if role == 'expert':
        if ctx.get('evidence_root'):
            reads.append(ctx['evidence_root'])
        reads += [prior['evidence_root'] for prior in ctx.get('prior_runs', [])]
        reads += [entry['evidence'] for entry in ctx.get('historical_pending_feedback', [])]
    reads += [entry['path'] for entry in ctx.get('handoff', {}).get('inputs', [])]
    knowledge = ctx.get('knowledge')
    if knowledge:
        reads += [knowledge['context'], knowledge['command'][0], knowledge['command'][1]]
        for claim in ctx['claims'] + ctx.get('claim_history', []):
            for ref in claim.get('evidence', []) + claim.get('counterevidence', []):
                if ref.get('availability') != 'access_denied':
                    path = Path(ref['source'])
                    if path.resolve().is_relative_to(Path(ref['storage']).resolve()):
                        reads.append(str(path))
    policy = tool_policy(tree, editable=comp.get('editable', []) if role == 'designer' else [],
                         scratch=comp.get('scratch', []) if role == 'designer' else [],
                         protected=['.opc', '.opc/**', *comp.get('frozen', []), *comp.get('evaluator_files', [])],
                         reads=reads)
    if ctx.get('tool_policy') is not None:
        policy = ctx['tool_policy']
    # Tool-owned temp/home directories do not expose sibling Call receipts.
    home, temp = log_dir / 'tool-home', log_dir / 'tool-tmp'
    home.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    return {**policy, 'read': list(policy['read']),
            'write': [*policy['write'], str(home.resolve()), str(temp.resolve())],
            'env': {'HOME': str(home.resolve()), 'TMPDIR': str(temp.resolve()),
                    'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                    'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}}


def codex_policy_args(policy: dict) -> list[str]:
    """Native tools use least privilege, independently of trusted CLI transport.

    Profile vocabulary: https://learn.chatgpt.com/docs/permissions .
    """
    filesystem = {':minimal': 'read', **{p: 'read' for p in policy['read']},
                  **{p: 'write' for p in policy['write']}}
    table = '{' + ','.join(json.dumps(k) + '=' + json.dumps(v) for k, v in filesystem.items()) + '}'
    configs = {'default_permissions': 'archa-task', 'approval_policy': 'never',
               'shell_environment_policy.inherit': 'none', 'shell_environment_policy.set': policy['env'],
               'web_search': 'disabled', 'apps._default.default_tools_enabled': False,
               'features.multi_agent': False, 'features.multi_agent_v2': False,
               'features.shell_snapshot': False, 'features.js_repl': False,
               'features.code_mode': False, 'features.apps': False,
               'features.memories': False, 'agents.enabled': False,
               'features.plugins': False, 'features.browser_use': False,
               'features.browser_use_external': False, 'features.in_app_browser': False,
               'features.skip_host_skill_discovery': True, 'features.skill_mcp_dependency_install': False,
               'permissions.archa-task.network.enabled': False}
    argv = ['-c', 'permissions.archa-task.filesystem=' + table]
    for key, value in configs.items():
        if isinstance(value, dict):
            value = '{' + ','.join(json.dumps(k) + '=' + json.dumps(v) for k, v in value.items()) + '}'
        else:
            value = json.dumps(value)
        argv += ['-c', key + '=' + value]
    # Disable user-supplied remote/MCP/plugin tools, which have separate access
    # authorities from the native command/file permission profile.
    argv += ['-c', 'mcp_servers={}', '-c', 'plugins={}']
    return argv


def preparation_policy(root: Path, task_id: str, revision: str, *, frozen: bool = False) -> dict:
    """Preparation edits candidate integration, never runtime or frozen history."""
    editable = ['.opc/eval/**', '.opc/components/**', '.opc/context/**', '.opc/profiles/**']
    if not frozen:
        editable.append('.opc/tasks/%s/revisions/%s/**' % (task_id, revision))
    # Runtime, ledger, workers configuration and historical contracts remain
    # outside the model's write authority.
    policy = tool_policy(root, editable=editable, scratch=[], protected=[])
    policy['limitations'].append('preparation root files such as .opc/project.json remain read-only; only candidate integration subdirectories are writable')
    return policy


def validate_cli_boundary_args(backend: str, args: list[str]) -> None:
    """Backend flags cannot widen the Engine's task tool authorization."""
    from .model import OPCError
    for index, arg in enumerate(args):
        if backend == 'codex':
            blocked = arg.startswith(('--dangerously-', '--sandbox', '--add-dir', '--approve-for-me',
                                      '--worktree', '--search', '--remote', '--enable', '--profile', '--cd', '--yolo', '--full-auto', '-s', '-C', '-p'))
            config = args[index + 1] if arg in ('-c', '--config') and index + 1 < len(args) else arg[9:] if arg.startswith('--config=') else arg[2:] if arg.startswith('-c') and arg != '-c' else None
            if config is not None:
                key = config.split('=', 1)[0].strip()
                blocked = blocked or key not in ('model', 'model_reasoning_effort')
        else:
            blocked = arg.startswith(('--permission-mode', '--add-dir', '--patch', '--from-default-profile'))
        if blocked:
            raise OPCError(backend + ' argument conflicts with task tool boundary: ' + arg)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('archa-tool-boundary: ' + str(exc), file=sys.stderr)
        sys.exit(125)
