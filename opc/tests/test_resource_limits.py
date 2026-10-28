"""Exercise unlimited preparation, dispatch and explicit local resource caps."""
import json
from types import SimpleNamespace

import pytest

from opc.adapters.codex import CodexWorker
from opc.adapters.dsh import DshWorker
from opc.core.config import TaskSpec
from opc.core.model import Cost, OPCError, BudgetExhausted
from opc.core.worker_config import CONFIG_PATH, load_budget_config
from opc.scaffold import init
from opc.scaffold.onboard import onboard
from opc.tests.conftest import task, write


def settings(root, caps):
    write(root / CONFIG_PATH, json.dumps({'budget': caps}))


def test_new_project_has_unlimited_resources(tmp_path):
    init(tmp_path, 'demo', 'Demo', 'main', 't-main', True)
    spec = TaskSpec.load(tmp_path, 't-main')
    assert spec.budget.max_tokens is spec.budget.max_wall_seconds is None
    assert load_budget_config(tmp_path) == {'max_tokens': None, 'max_wall_seconds': None}
    assert CodexWorker({}).timeout is None
    assert DshWorker({}).timeout is None


@pytest.mark.parametrize('caps,expected', [({}, (None, 600)),
    ({'max_tokens': 17}, (17, 600)), ({'max_wall_seconds': None}, (None, None)),
    ({'max_tokens': None, 'max_wall_seconds': 12.5}, (None, 12.5))])
def test_local_limits_override_only_explicit_fields(make_project, caps, expected):
    root = make_project()
    settings(root, caps)
    spec = TaskSpec.load(root, 't-toy')
    assert (spec.budget.max_tokens, spec.budget.max_wall_seconds) == expected


@pytest.mark.parametrize('caps', [{'max_tokens': True}, {'max_tokens': 1.5},
    {'max_tokens': 0}, {'max_wall_seconds': -1}, {'max_wall_seconds': float('inf')},
    {'max_wall_seconds': 'unlimited'}, {'max_token': 10}, None])
def test_invalid_limits_rejected(make_project, caps):
    root = make_project()
    settings(root, caps)
    with pytest.raises(OPCError):
        TaskSpec.load(root, 't-toy')


def test_unlimited_engine_keeps_dispatching_with_unknown_usage(make_project, engine_for):
    root = make_project()
    settings(root, {'max_tokens': None, 'max_wall_seconds': None})
    e = engine_for(root)
    e.enable_delivery()
    e.open_run()
    e.ledger.charge(e.run_id, None, 'expert', Cost(10**9, 10**9, None))
    e.ledger.event(e.run_id, 'accounting_unknown', reason='missing receipt')
    e.admit()
    e.hard_check()
    assert e.budget_left()['wall_seconds'] is None
    assert e.ledger.unresolved_accounting(e.run_id)


@pytest.mark.parametrize('key', ['max_tokens', 'max_wall_seconds'])
def test_explicit_limit_still_stops_execution(make_project, engine_for, key):
    root = make_project()
    settings(root, {'max_tokens': None, 'max_wall_seconds': None, key: 10})
    e = engine_for(root)
    e.open_run()
    e.ledger.charge(e.run_id, None, 'expert', Cost(11, 11, None))
    with pytest.raises(BudgetExhausted, match=key):
        e.hard_check()


def test_local_budget_change_requires_new_run(make_project, engine_for):
    root = make_project()
    settings(root, {'max_wall_seconds': None})
    e = engine_for(root)
    e.open_run()
    settings(root, {'max_wall_seconds': 100})
    with pytest.raises(OPCError, match='changed|digest|new.run'):
        engine_for(root).open_run()


def test_onboard_without_budget_or_usage_dispatches_and_preserves_unknown(make_project, monkeypatch):
    root = make_project()
    settings(root, {'max_tokens': None, 'max_wall_seconds': None})
    calls = []
    def run(self, role, prompt, tree, log, sandbox, schema):
        calls.append(role)
        assert self.timeout is None
        log.mkdir(parents=True)
        evidence = log / 'checks.txt'
        evidence.write_text('observed preparation checks')
        return SimpleNamespace(ok=True, call_id='test', cost=Cost(1, 7, None),
            extra={'usage_complete': False}, error=''), json.dumps({
            'state': 'ready', 'reason': 'prepared', 'evidence': [evidence.relative_to(root).as_posix()]})
    monkeypatch.setattr(CodexWorker, '_run', run)
    result = onboard(root, 'codex', task_id='t-toy')
    assert result['ok'], result
    assert calls == ['onboard']
    from opc.core.ledger import Ledger
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    rid = ledger.runs()[-1]['run_id']
    assert ledger.events(rid, 'host_usage_unknown')
    assert ledger.unresolved_accounting(rid)
    # Recording absent host usage must preserve readiness when there is no cap.
    assert onboard(root, 'codex', task_id='t-toy', record_usage_only=True)['ok']


def test_onboard_explicit_token_only_cap_persists(make_project):
    root = make_project()
    settings(root, {'max_wall_seconds': None})
    result = onboard(root, 'codex', task_id='t-toy', max_tokens=10,
                     prior_tokens=10, record_usage_only=True)
    assert result['preparation'] == 'budget_exhausted'
    assert load_budget_config(root) == {'max_tokens': 10, 'max_wall_seconds': None}


@pytest.mark.parametrize('token_cap', [None, 100])
def test_unknown_token_receipt_blocks_only_explicit_token_cap(make_project, engine_for, token_cap):
    root = make_project()
    settings(root, {'max_tokens': token_cap, 'max_wall_seconds': 100})
    e = engine_for(root)
    e.enable_delivery()
    e.open_run()
    e.ledger.event(e.run_id, 'accounting_unknown', reason='token usage missing')
    if token_cap is None:
        e.admit()
    else:
        with pytest.raises(OPCError, match='accounting incomplete'):
            e.admit()


def test_explicit_unlimited_config_overrides_previous_preparation_cap(make_project, engine_for):
    root = make_project()
    onboard(root, 'codex', task_id='t-toy', max_tokens=100, max_wall_seconds=100,
            prior_tokens=5, prior_wall_seconds=1, record_usage_only=True)
    settings(root, {'max_tokens': None, 'max_wall_seconds': None})
    e = engine_for(root)
    assert e.task.budget.max_tokens is e.task.budget.max_wall_seconds is None
    assert e.ledger.task_totals('t-toy')['tokens'] == 5
