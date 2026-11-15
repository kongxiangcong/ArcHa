"""Single role dispatch with explicit prepared and published output boundaries."""
import os
import re
from .topic_workspace import TopicWorkspace
from ..adapters.topic_prompts import prompt
from ..adapters.topic_worker import invoke


class TopicEngine:
    def __init__(self, project, topic):
        self.workspace = TopicWorkspace(project, topic)

    def run(self):
        with self.lifecycle():
            self.run_locked()
        return self.workspace.status()

    def resume(self, add_rounds=None):
        with self.lifecycle():
            self.workspace.resume(add_rounds)
            self.run_locked()
        return self.workspace.status()

    def run_locked(self):
        status = self.workspace.status()
        while status['status'] == 'IN_PROGRESS':
            status = self.step_locked()
        return status

    def step(self):
        with self.lifecycle():
            self.step_locked()
        return self.workspace.status()

    def lifecycle(self):
        from .topic_control import lifecycle
        return lifecycle(self.workspace)

    def step_locked(self):
        """Dispatch once with the project lock held and recovery complete."""
        w = self.workspace
        from .topic_control import check_stop
        check_stop(w)
        status = w.status()
        role = status['next_action']
        if role not in {'expert', 'executor', 'expert_finalize'}:
            return status
        goal = (w.path / 'GOAL.md').read_text()
        # A template with headings but no content is not an exploration goal.
        if not any(line.strip() and not line.startswith('#') for line in re.sub(r'<!--.*?-->', '', goal, flags=re.S).splitlines()):
            raise ValueError('GOAL.md is empty; fill Objective, Environment entry and Completion criteria')
        directory = w.path / 'steps' / f'step-{status["current_round"]:02d}'
        directory.mkdir(exist_ok=True)
        stage = directory / '.staging.expert'
        if stage.exists() or (directory / '.staging.commit').exists():
            raise ValueError('unfinished Expert output requires recovery before dispatch')
        if role.startswith('expert'):
            stage.mkdir()
            state_file = stage / 'STATE.md'
            output_file = state_file if role == 'expert_finalize' else stage / 'probe.md'
            state_file.write_text((w.path / 'STATE.md').read_text(), encoding='utf-8')
        else:
            state_file, output_file = w.path / 'STATE.md', directory / '.staging.result.md'
        invoke(w, role, prompt(w, role, directory, state_file, output_file),
               state_file, output_file, directory / f'.{role}.log')
        if role.startswith('expert'):
            w.commit_expert(directory, status['max_rounds'], finalize=role == 'expert_finalize')
        else:
            if not output_file.read_text().strip():
                raise ValueError('Executor result is empty')
            os.replace(output_file, directory / 'result.md')
        return w.status()
