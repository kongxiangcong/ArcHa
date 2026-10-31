#!/usr/bin/env python3
"""Run local benchmark commands with Landlock file boundaries and no sockets.

Linux x86_64, Landlock ABI >= 3. This launcher is for local execution tools;
model API transport stays in the trusted orchestrator, outside this process.
"""
import argparse
import os
from pathlib import Path
import sys


# Share the actual kernel boundary with Worker tool runners.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from opc.core.tool_boundary import restrict as restrict_tools


def restrict(project, runtime):
    restrict_tools([project], [project], [runtime])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    runtime = Path(__file__).resolve().parents[1] / '.runtime'
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        parser.error('provide a command after the project path')
    for name in ['.home', '.tmp']:
        (project / name).mkdir(exist_ok=True)
    os.chdir(project)
    env = {'PATH': f'{runtime}/python/bin:{runtime}/cmake/bin:/usr/bin:/bin',
           'HOME': str(project / '.home'), 'TMPDIR': str(project / '.tmp'),
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONNOUSERSITE': '1',
           'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
           'MPLCONFIGDIR': str(project / '.home/matplotlib'),
           'PYTHONPATH': ':'.join(str(project / p) for p in
               ['source/src/deepstack', 'source/src/tilesight', 'source/tests'])}
    restrict(project, runtime)
    os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
