#!/usr/bin/env python3
"""Prepare four fixed, independent benchmark workspaces without running agents."""
import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = '17e21bf54115e11b9e7c6edc0b2d1723d25d022b'
RAM = 'be93be78055d922aa1d4d33e15bcc8f2b0c61a9d'
TASKS = ['deepstack-development', 'ramulator2-optimization',
         'deepstack-exploration', 'deepstack-end-to-end']


def export(repo, commit, target):
    target.mkdir(parents=True, exist_ok=True)
    archive = subprocess.check_output(['git', '-C', str(repo), 'archive', commit])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter='data')


def digest_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.parts
            and not set(p.relative_to(root).parts).intersection({'.tmp', '.home', 'build', 'results', '__pycache__', '.pytest_cache'})
            and p.name not in {'libramulator.so', 'exam-build.log'}}


def prepare_runtime():
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    if not (runtime / 'python/bin/python3.11').exists():
        base = Path('/root/.local/share/uv/python/cpython-3.11.18-linux-x86_64-gnu')
        shutil.copytree(base, runtime / 'python', symlinks=True)
        shutil.copytree('/tmp/archa-deepstack-timing/venv/lib/python3.11/site-packages',
                        runtime / 'python/lib/python3.11/site-packages', dirs_exist_ok=True,
                        symlinks=True)
    if not (runtime / 'cmake/bin/cmake').exists():
        shutil.copytree('/tmp/ramulator-build-tools/lib/python3.12/site-packages/cmake/data',
                        runtime / 'cmake', symlinks=True)
    shutil.copy2(ROOT.parent / 'docs/reports/deepstack-timing-20261031/requirements-resolved.txt',
                 runtime / 'requirements-resolved.txt')
    return runtime


def prepare(name, runtime):
    task = ROOT / name
    project = task / 'runs/prepared/project'
    if project.exists():
        print(f'{name}: workspace already exists; leaving it unchanged', flush=True)
        return
    project.mkdir(parents=True)
    shutil.copy2(task / 'TASK.md', project / 'TASK.md')
    starter = task / 'starter'
    if starter.exists():
        shutil.copytree(starter, project, dirs_exist_ok=True)
    if name == 'deepstack-development':
        source = {'upstream': 'https://github.com/tile-ai/DeepStack', 'commit': DS,
                  'distribution': 'interface-only derived task; solution withheld'}
    elif name.startswith('deepstack'):
        export('/root/DeepStack', DS, project / 'source')
        source = {'upstream': 'https://github.com/tile-ai/DeepStack', 'commit': DS,
                  'distribution': 'complete fixed original release; independent copy'}
        paper = ROOT / 'deepstack/materials/deepstack-paper.pdf'
        if paper.exists():
            (project / 'references').mkdir()
            shutil.copy2(paper, project / 'references/deepstack-paper.pdf')
    else:
        export('/root/ramulator2', RAM, project / 'source')
        dependency_commits = {}
        for dep in ['argparse', 'spdlog', 'yaml-cpp']:
            repo = Path('/root/ramulator2/ext') / dep
            sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
            export(repo, sha, project / 'source/ext' / dep)
            dependency_commits[dep] = sha
        source = {'upstream': 'https://github.com/CMU-SAFARI/ramulator2', 'commit': RAM,
                  'distribution': 'complete fixed source and vendored build dependencies',
                  'dependencies': dependency_commits}
        (project / 'build.sh').write_text('''#!/bin/sh
set -eu
cd "$(dirname "$0")"
cmake -S source -B build -DCMAKE_BUILD_TYPE=Release \\
  -DFETCHCONTENT_SOURCE_DIR_YAML-CPP="$PWD/source/ext/yaml-cpp" \\
  -DFETCHCONTENT_SOURCE_DIR_SPDLOG="$PWD/source/ext/spdlog" \\
  -DFETCHCONTENT_SOURCE_DIR_ARGPARSE="$PWD/source/ext/argparse"
cmake --build build -j 2
''')
        (project / 'build.sh').chmod(0o755)
    (project / 'SOURCE.json').write_text(json.dumps(source, indent=2)+'\n')
    (project / '.gitignore').write_text('.home/\n.tmp/\n__pycache__/\nbuild/\nsource/libramulator.so\nresults/\n')
    subprocess.run(['git', 'init', '-q', str(project)], check=True)
    subprocess.run(['git', '-C', str(project), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(project), '-c', 'user.name=Benchmark preparation',
                    '-c', 'user.email=benchmark@localhost', 'commit', '-qm', 'Fixed benchmark starter'], check=True)
    manifest = {'task': name, 'source': source, 'files': digest_tree(project),
                'runtime': str(runtime), 'formal_exam': False}
    (project.parent / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'{name}: prepared {project}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tasks', nargs='*', choices=TASKS)
    args = parser.parse_args()
    runtime = prepare_runtime()
    for name in args.tasks or TASKS:
        prepare(name, runtime)
