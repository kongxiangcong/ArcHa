"""Execution allowance changes use the existing Run/ledger boundary."""
import json
import pytest

from opc.core.engine import Engine
from opc.core.model import Cost, OPCError, BudgetExhausted
from opc.tests.conftest import task


def prepare_switch(make_project, *, hard=None):
    contract = task(workers={'expert': {}, 'designer': {}}, budget={'max_wall_seconds': 600, 'max_tokens': 1000})
    if hard:
        contract['hard_limits'] = hard
    root = make_project(tsk=contract)
    engine = Engine(root, 't-toy', log=lambda _: None)
    with engine.ledger.writer():
        engine.open_run()
    engine.ledger.charge(engine.run_id, None, 'expert', Cost(80, 200, None))
    engine.ledger.set_run_state(engine.run_id, 'closed', 'stopped')
    (root / '.opc/local/workers.json').write_text(json.dumps({'expert': {'kind': 'dsh'}}))
    return root, engine


def test_explicit_backend_switch_resets_only_execution_allowance(make_project):
    root, old = prepare_switch(make_project)
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer():
        new.open_run(new_run=True, switch_backend=True)
    assert new.spent()['tokens'] == 0 and new.spent()['wall_seconds'] == 0
    assert new.ledger.task_totals('t-toy')['tokens'] == 200
    new.ledger.charge(new.run_id, None, 'designer', Cost(3, 9, None))
    new.ledger.set_run_state(new.run_id, 'paused')
    resumed = Engine(root, 't-toy', run_id=new.run_id, log=lambda _: None)
    with resumed.ledger.writer():
        resumed.open_run()
    assert resumed.spent()['tokens'] == 9
    resumed.ledger.set_run_state(resumed.run_id, 'closed', 'stopped')
    ordinary = Engine(root, 't-toy', log=lambda _: None)
    with ordinary.ledger.writer():
        ordinary.open_run(new_run=True)
    assert ordinary.spent()['tokens'] == 9
    assert ordinary.summary()['budget']['origin']['tokens'] == 200


def test_new_run_with_changed_default_does_not_reset_without_ack(make_project):
    root, old = prepare_switch(make_project)
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer():
        new.open_run(new_run=True)
    assert new.spent()['tokens'] == 200
    with pytest.raises(OPCError, match='new Run'):
        new.open_run(switch_backend=True)


def test_switch_preserves_lifetime_hard_limit(make_project):
    root, old = prepare_switch(make_project, hard={'max_tokens': 200})
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer():
        new.open_run(new_run=True, switch_backend=True)
    with pytest.raises(BudgetExhausted, match='hard limit'):
        new.hard_check()


def test_switch_retains_history_but_does_not_block_on_old_quota_unknown(make_project):
    root, old = prepare_switch(make_project)
    old.ledger.event(old.run_id, 'accounting_unknown', reason='old provider missing usage')
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer():
        new.open_run(new_run=True, switch_backend=True)
    new.hard_check()
    assert new.ledger.unresolved_accounting(old.run_id)
    assert new.unresolved_usage(old.run_id) == []


def test_same_backend_cannot_reset_allowance(make_project):
    root, old = prepare_switch(make_project)
    (root / '.opc/local/workers.json').write_text(json.dumps({'expert': {'kind': 'codex'}}))
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer(), pytest.raises(OPCError, match='explicit change'):
        new.open_run(new_run=True, switch_backend=True)
    assert len(new.ledger.runs()) == 1


def test_late_historical_correction_does_not_charge_new_execution(make_project):
    root, old = prepare_switch(make_project)
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer():
        new.open_run(new_run=True, switch_backend=True)
    old.ledger.charge(old.run_id, None, 'accounting reconciliation', Cost(12, 40, None))
    assert new.spent()['tokens'] == 0 and new.spent()['wall_seconds'] == 0
    assert new.summary()['budget']['historical_used']['tokens'] == 240


def test_lifetime_wall_limit_bounds_inflight_allowance_after_switch(make_project):
    root, old = prepare_switch(make_project, hard={'max_wall_seconds': 100})
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer():
        new.open_run(new_run=True, switch_backend=True)
    assert new.budget_left()['wall_seconds'] == 20


def test_independent_project_hard_total_survives_tighter_task_limit(make_project):
    root, old = prepare_switch(make_project, hard={'max_tokens': 500})
    project = root / '.opc/project.json'
    config = json.loads(project.read_text())
    config['hard_limits'] = {'max_tokens': 800}
    project.write_text(json.dumps(config))
    from opc.tests.conftest import git
    git(root, 'add', '.opc/project.json')
    git(root, 'commit', '-qm', 'configure project cap')
    new = Engine(root, 't-toy', log=lambda _: None)
    other = new.ledger.create_run(task_id='other-task', revision='r0001', task_digest='test',
        component='toy', base_commit=old.ledger.run(old.run_id)['base_commit'], evaluator_digest='test',
        toolchain_digest='test', champion_ref='', direction='')
    new.ledger.charge(other, None, 'expert', Cost(0, 600, None))
    with new.ledger.writer():
        new.open_run(new_run=True, switch_backend=True)
    with pytest.raises(BudgetExhausted, match='project lifetime hard limit'):
        new.hard_check()


def test_explicit_switch_accepts_quiescent_pause_without_changing_old_run(make_project):
    root, old = prepare_switch(make_project)
    old.ledger.set_run_state(old.run_id, 'paused')
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer():
        new.open_run(new_run=True, switch_backend=True)
    assert new.spent()['tokens'] == 0
    assert old.ledger.run(old.run_id)['state'] == 'paused'
    resumed = Engine(root, 't-toy', run_id=old.run_id, log=lambda _: None)
    with resumed.ledger.writer():
        resumed.open_run()
    assert resumed.worker_spec('expert').kind == 'codex'


def test_explicit_switch_cannot_bypass_unknown_prior_execution(make_project):
    root, old = prepare_switch(make_project)
    old.ledger.set_run_state(old.run_id, 'paused')
    old.ledger.begin_call(old.run_id, None, 'expert', {'tree':'old'}, 'missing.json')
    new = Engine(root, 't-toy', log=lambda _: None)
    with new.ledger.writer(), pytest.raises(OPCError, match='execution unknown'):
        new.open_run(new_run=True, switch_backend=True)
    assert len(new.ledger.runs()) == 1
