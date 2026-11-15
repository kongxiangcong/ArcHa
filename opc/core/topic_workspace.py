"""Topic authoritative documents and prepared-output publication."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil

from .platform import lock_writer, unlock_writer
from ..scaffold.templates import STATE, goal_template

STATUSES = {'IN_PROGRESS', 'COMPLETED', 'BLOCKED', 'BUDGET_EXHAUSTED'}


def parse_state(text):
    lines = text.splitlines()
    if not lines or lines[0] != '# Exploration State':
        raise ValueError('STATE.md: missing # Exploration State header')
    header = []
    for line in lines[1:]:
        if not line.strip():
            break
        header.append(line)
    values = {}
    for line in header:
        key, separator, value = line.partition(':')
        if not separator or key not in {'STATUS', 'MAX_ROUNDS'}:
            raise ValueError('STATE.md: invalid metadata: ' + line)
        if key in values:
            raise ValueError('STATE.md: duplicate ' + key)
        values[key] = value.strip()
    for key in ('STATUS', 'MAX_ROUNDS'):
        if key not in values:
            raise ValueError('STATE.md: missing ' + key)
    if values['STATUS'] not in STATUSES:
        raise ValueError('STATE.md: invalid STATUS')
    if not re.fullmatch('[1-9][0-9]*', values['MAX_ROUNDS']):
        raise ValueError('STATE.md: MAX_ROUNDS must be a positive integer')
    return values['STATUS'], int(values['MAX_ROUNDS'])


class TopicWorkspace:
    def __init__(self, project, topic):
        self.project = Path(project).resolve()
        if not self.project.is_dir():
            raise ValueError('project must be an existing directory')
        if not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', topic):
            raise ValueError('topic must be a lowercase portable slug')
        self.topic = topic
        self.control = self.project / '.archa'
        self.path = self.control / 'topics' / topic
        if self.path.resolve() != self.path:
            raise ValueError('topic path must not be redirected')

    @contextmanager
    def writer(self):
        self.control.mkdir(exist_ok=True)
        fd = os.open(self.control / '.run.lock', os.O_CREAT | os.O_RDWR, 0o644)
        locked = False
        try:
            try:
                lock_writer(fd)
                locked = True
            except BlockingIOError:
                raise ValueError('project execution lock is held') from None
            yield
        finally:
            if locked:
                unlock_writer(fd)
            os.close(fd)

    def initialize(self, goal='', max_rounds=10, template='default'):
        if max_rounds <= 0:
            raise ValueError('MAX_ROUNDS must be a positive integer')
        goal_text = goal_template(template).format(goal=goal)
        with self.writer():
            self.path.mkdir(parents=True, exist_ok=True)
            (self.path / 'steps').mkdir(exist_ok=True)
            defaults = json.loads((Path(__file__).parents[1] / 'scaffold/topic_workers.json').read_text())
            files = {self.path / 'GOAL.md': goal_text,
                     self.path / 'STATE.md': STATE.format(max_rounds=max_rounds),
                     self.control / 'workers.json': json.dumps(defaults, indent=2) + '\n'}
            for path, text in files.items():
                if not path.exists():
                    path.write_text(text, encoding='utf-8')
        return self.status()

    def state(self):
        return parse_state((self.path / 'STATE.md').read_text(encoding='utf-8'))

    def rounds(self):
        committed = []
        for directory in sorted((self.path / 'steps').iterdir()):
            if not directory.is_dir() or not directory.name.startswith('step-'):
                raise ValueError('invalid round directory: ' + directory.name)
            suffix = directory.name[5:]
            if not suffix.isdigit() or int(suffix) <= 0 or suffix != f'{int(suffix):02d}':
                raise ValueError('noncanonical round: ' + directory.name)
            probe, result = directory / 'probe.md', directory / 'result.md'
            if result.exists() and not probe.exists():
                raise ValueError('result without probe: ' + directory.name)
            if probe.exists():
                for file in (probe, result):
                    if file.exists() and not file.read_text(encoding='utf-8').strip():
                        raise ValueError('empty committed document: ' + str(file))
                committed.append((int(suffix), result.exists()))
        committed.sort()
        for index, (number, complete) in enumerate(committed, 1):
            if number != index or (index < len(committed) and not complete):
                raise ValueError('rounds must be contiguous with at most one pending probe')
        return committed

    def status(self):
        state, budget = self.state()
        rounds = self.rounds()
        completed = sum(complete for _, complete in rounds)
        if completed > budget or (rounds and not rounds[-1][1] and len(rounds) > budget):
            raise ValueError('MAX_ROUNDS does not cover committed rounds and pending probe')
        action = state.lower() if state != 'IN_PROGRESS' else (
            'executor' if rounds and not rounds[-1][1] else
            'expert_finalize' if completed == budget else 'expert')
        from .topic_control import activity
        error_path = self.path / '.last-error'
        try:
            error = error_path.read_text(encoding='utf-8')
        except FileNotFoundError:
            error = None
        return dict(**activity(self), topic=self.topic, status=state, max_rounds=budget, error=error,
                    completed_rounds=completed, next_action=action,
                    current_round=(len(rounds) if action in {'executor', 'expert_finalize'} or state != 'IN_PROGRESS'
                                   else completed + 1),
                    publishing=any((self.path / 'steps').glob('step-*/.staging.commit')))

    def resume(self, add_rounds=None):
        """Update user authorization under the caller's execution lifecycle lock."""
        if add_rounds is not None and (type(add_rounds) is not int or add_rounds <= 0):
            raise ValueError('add-rounds must be a positive integer')
        status = self.status()
        if status['status'] == 'COMPLETED':
            if add_rounds is not None:
                raise ValueError('COMPLETED topic cannot accept additional rounds')
            return
        state = status['status']
        if state == 'BLOCKED' or (state == 'BUDGET_EXHAUSTED' and add_rounds is not None):
            state = 'IN_PROGRESS'
        budget = status['max_rounds'] + (add_rounds or 0)
        if state == status['status'] and budget == status['max_rounds']:
            return
        path = self.path / 'STATE.md'
        lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
        end = next((i for i, line in enumerate(lines[1:], 1) if not line.strip()), len(lines))
        temporary = self.path / '.STATE.resume.md'
        temporary.write_text(f'# Exploration State\nSTATUS: {state}\nMAX_ROUNDS: {budget}\n'
                             + ''.join(lines[end:]), encoding='utf-8')
        os.replace(temporary, path)

    def commit_expert(self, directory, max_rounds, *, finalize=False):
        """Validate the complete draft before entering recoverable publication."""
        stage = directory / '.staging.expert'
        text = (stage / 'STATE.md').read_text(encoding='utf-8')
        state, budget = parse_state(text)
        if not finalize and state not in {'IN_PROGRESS', 'COMPLETED', 'BLOCKED'}:
            raise ValueError('Expert returned invalid normal-turn STATUS')
        if budget != max_rounds:
            raise ValueError('Expert cannot change MAX_ROUNDS')
        probe = stage / 'probe.md'
        if finalize:
            state = 'COMPLETED' if state == 'COMPLETED' else 'BUDGET_EXHAUSTED'
        if state == 'IN_PROGRESS':
            if not probe.is_file() or not probe.read_text(encoding='utf-8').strip():
                raise ValueError('Expert probe is missing or empty')
        else:
            probe.unlink(missing_ok=True)
        # Normalize only the metadata header, retaining the complete cognitive body.
        lines = text.splitlines(keepends=True)
        end = next((i for i, line in enumerate(lines[1:], 1) if not line.strip()), len(lines))
        body = ''.join(lines[end:])
        (stage / 'STATE.md').write_text(
            f'# Exploration State\nSTATUS: {state}\nMAX_ROUNDS: {max_rounds}\n' + body,
            encoding='utf-8')
        stage.rename(directory / '.staging.commit')
        self.publish_expert(directory)

    def recover(self):
        """Under the writer lock, after owned processes have ended, finish publication."""
        for directory in sorted((self.path / "steps").glob("step-*")):
            if (directory / ".staging.commit").exists():
                self.publish_expert(directory)
            stage = directory / ".staging.expert"
            if stage.exists():
                shutil.rmtree(stage)
            for name in (".staging.result.md", ".expert.prompt.md",
                         ".executor.prompt.md", ".expert_finalize.prompt.md"):
                (directory / name).unlink(missing_ok=True)

    def publish_expert(self, directory):
        commit = directory / '.staging.commit'
        for name, target in [('STATE.md', self.path / 'STATE.md'), ('probe.md', directory / 'probe.md')]:
            source = commit / name
            if source.exists():
                os.replace(source, target)
        commit.rmdir()
