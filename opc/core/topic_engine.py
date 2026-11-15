"""Single role dispatch with explicit prepared and published output boundaries."""
import os
from .topic_workspace import TopicWorkspace
from ..adapters.topic_prompts import prompt
from ..adapters.topic_worker import invoke


class TopicEngine:
    def __init__(self, project, topic):
        self.workspace = TopicWorkspace(project, topic)

    def step(self):
        w = self.workspace
        with w.writer():
            w.recover()
            return self.step_locked()

    def step_locked(self):
        """Dispatch once with the project lock held and recovery complete."""
        w = self.workspace
        status = w.status()
        role = status['next_action']
        if role not in {'expert', 'executor', 'expert_finalize'}:
            return status
        goal = (w.path / 'GOAL.md').read_text()
        # A template with headings but no content is not an exploration goal.
        if not any(line.strip() and not line.startswith('#') for line in goal.splitlines()):
            raise ValueError('GOAL.md is empty; fill Objective, Environment entry and Completion criteria')
        if role == 'expert_finalize':
            raise ValueError('round budget reached; finalization is not available in this version')
        directory = w.path / 'steps' / f'step-{status["current_round"]:02d}'
        directory.mkdir(exist_ok=True)
        stage = directory / '.staging.expert'
        if stage.exists() or (directory / '.staging.commit').exists():
            raise ValueError('unfinished Expert output requires recovery before dispatch')
        if role == 'expert':
            stage.mkdir()
            state_file, output_file = stage / 'STATE.md', stage / 'probe.md'
            state_file.write_text((w.path / 'STATE.md').read_text(), encoding='utf-8')
        else:
            state_file, output_file = w.path / 'STATE.md', directory / '.staging.result.md'
        invoke(w, role, prompt(w, role, directory, state_file, output_file),
               state_file, output_file, directory / f'.{role}.log')
        if role == 'expert':
            w.commit_expert(directory, status['max_rounds'])
        else:
            if not output_file.read_text().strip():
                raise ValueError('Executor result is empty')
            os.replace(output_file, directory / 'result.md')
        return w.status()
