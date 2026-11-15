"""Display topic paths; initialize only through the deployed local entry."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def layout(project_root: Path, topic: str) -> dict:
    root = project_root.resolve()
    if not root.is_dir():
        raise ValueError('project root must be an existing directory')
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', topic):
        raise ValueError('topic must be a lowercase portable slug')
    control = root / '.archa'
    directory = control / 'topics' / topic
    if directory.resolve() != directory:
        raise ValueError('topic path must not be redirected')
    return {'project': str(root), 'topic': topic, 'entrypoint': str(control / 'archa.py'),
            'workers': str(control / 'workers.json'), 'topic_directory': str(directory),
            'goal': str(directory / 'GOAL.md'), 'state': str(directory / 'STATE.md'),
            'steps': str(directory / 'steps'), 'report': str(directory / 'PROGRESS_LOG.md')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('paths', 'init'))
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--topic', required=True)
    parser.add_argument('--goal', default='')
    parser.add_argument('--max-rounds', type=int, default=10)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        paths = layout(args.project_root, args.topic)
        if args.command == 'init' and args.apply:
            if not Path(paths['entrypoint']).is_file():
                raise ValueError('deploy with skills/archa-discuss/scripts/initialize.py first')
            return subprocess.call([sys.executable, paths['entrypoint'], 'init', '-p', paths['project'],
                                    '--topic', args.topic, '--goal', args.goal, '--max-rounds', str(args.max_rounds)])
        print(json.dumps(paths, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(2, f'error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
