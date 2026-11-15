"""HTTP admission delegates exclusivity and cleanup to the engine lifecycle."""
from concurrent.futures import Future
import logging
from threading import Thread

from ..core.engine import TopicEngine


def resume(workspace, add_rounds=None):
    admitted = Future()

    def execute():
        engine = TopicEngine(workspace.project, workspace.topic)
        try:
            with engine.lifecycle():
                status = workspace.status()
                if status['status'] == 'COMPLETED':
                    raise ValueError('COMPLETED topic cannot be reopened')
                if status['status'] == 'BUDGET_EXHAUSTED' and add_rounds is None:
                    raise ValueError('BUDGET_EXHAUSTED requires additional rounds')
                workspace.resume(add_rounds)
                admitted.set_result({'accepted': True, 'execution_id': workspace.status()['execution']['id']})
                engine.run_locked()
        except Exception as exc:
            if not admitted.done():
                admitted.set_exception(exc)
            else:
                # The lifecycle persists the failure for all readers.
                logging.getLogger(__name__).warning('Topic %s stopped: %s', workspace.topic, exc)

    Thread(target=execute, name=f'archa-{workspace.topic}', daemon=False).start()
    return admitted.result()
