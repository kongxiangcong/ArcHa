"""HTTP admission delegates exclusivity and cleanup to the engine lifecycle."""
from concurrent.futures import Future
import logging
from threading import Thread

from ..core.engine import TopicEngine


def resume(workspace, add_rounds=None, debug_probes=None):
    return dispatch(workspace, add_rounds, debug_probes)


def revise(workspace, feedback):
    return dispatch(workspace, feedback=feedback)


def dispatch(workspace, add_rounds=None, debug_probes=None, feedback=None):
    admitted = Future()

    def execute():
        engine = TopicEngine(workspace.project, workspace.topic)
        try:
            with engine.lifecycle('expert_revise' if feedback is not None else None):
                if feedback is not None:
                    engine.prepare_revision(feedback)
                    admitted.set_result({'accepted': True, 'execution_id': workspace.status()['execution']['id']})
                    engine.step_locked(revise=True)
                    return
                status = workspace.status()
                if status['status'] == 'COMPLETED':
                    raise ValueError('COMPLETED topic cannot be reopened')
                if status['status'] == 'BUDGET_EXHAUSTED' and add_rounds is None:
                    raise ValueError('BUDGET_EXHAUSTED requires additional rounds')
                workspace.resume(add_rounds)
                pause_existing = engine.configure_debug(debug_probes)
                admitted.set_result({'accepted': True, 'execution_id': workspace.status()['execution']['id']})
                engine.run_locked(pause_existing)
        except Exception as exc:
            if not admitted.done():
                admitted.set_exception(exc)
            else:
                # The lifecycle persists the failure for all readers.
                logging.getLogger(__name__).warning('Topic %s stopped: %s', workspace.topic, exc)

    Thread(target=execute, name=f'archa-{workspace.topic}', daemon=False).start()
    return admitted.result()
