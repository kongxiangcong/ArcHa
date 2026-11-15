"""Project-local topic commands."""
import argparse
import json
from pathlib import Path
import sys
from .core.topic_workspace import TopicWorkspace
from .core.topic_engine import TopicEngine


def main(argv=None):
    parser = argparse.ArgumentParser(prog='opc')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('init', 'step', 'run', 'resume', 'status', 'stop'):
        p = sub.add_parser(command)
        p.add_argument('-p', '--project', required=True)
        p.add_argument('--topic', required=True)
        if command == 'resume':
            p.add_argument('--add-rounds', type=int)
        if command == 'init':
            goal = p.add_mutually_exclusive_group()
            goal.add_argument('--goal', default='')
            goal.add_argument('--goal-file', type=Path)
            p.add_argument('--template', choices=('default', 'pim'), default='default')
            p.add_argument('--max-rounds', type=int, default=10)
    args = parser.parse_args(argv)
    try:
        workspace = TopicWorkspace(args.project, args.topic)
        if args.command == 'init':
            result = workspace.initialize(args.goal_file.read_text() if args.goal_file else args.goal, args.max_rounds, args.template)
        elif args.command == 'step':
            result = TopicEngine(args.project, args.topic).step()
        elif args.command == 'stop':
            from .core.topic_control import stop
            result = stop(workspace)
        elif args.command == 'run':
            result = TopicEngine(args.project, args.topic).run()
        elif args.command == 'resume':
            result = TopicEngine(args.project, args.topic).resume(args.add_rounds)
        else:
            result = workspace.status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command in {'run', 'resume'}:
            return {'COMPLETED': 0, 'IN_PROGRESS': 3, 'BLOCKED': 4, 'BUDGET_EXHAUSTED': 5}[result['status']]
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print('opc: error: ' + str(exc), file=sys.stderr)
        return 2
