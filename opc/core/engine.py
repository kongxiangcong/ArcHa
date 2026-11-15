"""Single role dispatch with explicit prepared and published output boundaries."""
import os
import re
from .workspace import TopicWorkspace
from ..adapters.prompts import prompt
from ..adapters.worker import invoke


class TopicEngine:
    def __init__(self, project, topic):
        self.workspace = TopicWorkspace(project, topic)

    def run(self, debug_probes=None):
        with self.lifecycle():
            self.run_locked(self.configure_debug(debug_probes))
        return self.workspace.status()

    def resume(self, add_rounds=None, debug_probes=None):
        with self.lifecycle():
            self.workspace.resume(add_rounds)
            self.run_locked(self.configure_debug(debug_probes))
        return self.workspace.status()

    def configure_debug(self, enabled):
        """Persist explicit user selection under the execution lock."""
        path = self.workspace.path / '.debug-probes'
        newly_enabled = enabled is True and not path.exists()
        if enabled is True:
            path.touch(exist_ok=True)
        elif enabled is False:
            path.unlink(missing_ok=True)
        return newly_enabled

    def run_locked(self, pause_existing=False):
        status = self.workspace.status()
        if pause_existing and status['next_action'] == 'executor':
            return status
        while status['status'] == 'IN_PROGRESS':
            status = self.step_locked()
            if status['debug_probes'] and status['next_action'] == 'executor':
                break
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
