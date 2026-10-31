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


def test_new_project_has_two_hour_time_budget(tmp_path):
    init(tmp_path, 'demo', 'Demo', 'main', 't-main', True)
    spec = TaskSpec.load(tmp_path, 't-main')
    assert spec.budget.max_tokens is None
    assert spec.budget.max_wall_seconds == 7200
    assert load_budget_config(tmp_path) == {'max_tokens': None, 'max_wall_seconds': 7200}
    assert CodexWorker({}).timeout is None
    assert DshWorker({}).timeout is None


@pytest.mark.parametrize('caps,expected', [({}, (None, 600)),
    ({'max_tokens': 17}, (17, 600)), ({'max_wall_seconds': None}, (None, 600)),
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
    t = task()
    t["budget"]["max_wall_seconds"] = None
    root = make_project(tsk=t)
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


def test_local_budget_change_does_not_change_existing_run(make_project, engine_for):
    root = make_project()
    settings(root, {'max_wall_seconds': None})
    e = engine_for(root)
    e.open_run()
    settings(root, {'max_wall_seconds': 100})
    resumed = engine_for(root)
    assert resumed.open_run() == e.run_id
    assert resumed.task.budget.max_wall_seconds == 600


def test_onboard_without_budget_or_usage_dispatches_and_preserves_unknown(make_project, monkeypatch):
    t = task()
    t["budget"]["max_wall_seconds"] = None
    root = make_project(tsk=t)
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
    rid = ledger.preparation_scope('t-toy')
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


def test_null_local_config_keeps_previous_preparation_cap(make_project, engine_for):
    root = make_project()
    onboard(root, 'codex', task_id='t-toy', max_tokens=100, max_wall_seconds=100,
            prior_tokens=5, prior_wall_seconds=1, record_usage_only=True)
    settings(root, {'max_tokens': None, 'max_wall_seconds': None})
    e = engine_for(root)
    assert e.effective_budget().max_tokens == 100
    assert e.effective_budget().max_wall_seconds == 100
    assert e.ledger.task_totals('t-toy')['tokens'] == 5


def test_default_task_budget_is_two_hours_without_attempt_cap(make_project, engine_for):
    root = make_project(tsk=task(budget={}))
    e = engine_for(root)
    e.run(max_attempts_now=0)
    assert e.task.budget.max_tokens is None
    assert e.task.budget.max_wall_seconds == 7200
    assert e.budget_left()['attempts'] is None
    assert e.summary()['budget']['limits']['wall_seconds'] == 7200


def test_task_usage_survives_independent_run_and_new_revision(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    e.run(max_attempts_now=0)
    e.ledger.charge(e.run_id, None, 'expert', Cost(601, 37, None))
    later = engine_for(root)
    later.open_run(new_run=True)
    assert later.spent()['wall_seconds'] >= 601
    assert later.spent()['tokens'] == 37
    with pytest.raises(BudgetExhausted, match='max_wall_seconds'):
        later.admit()
    t = task(revision='r0002')
    write(root / '.opc/tasks/t-toy/revisions/r0002/task.json', json.dumps(t))
    from opc.tests.conftest import git
    git(root, 'add', '.opc/tasks')
    git(root, 'commit', '-qm', 'new revision')
    newest = engine_for(root)
    newest.open_run(new_run=True)
    assert newest.spent()['tokens'] == 37
    with pytest.raises(BudgetExhausted, match='max_wall_seconds'):
        newest.admit()


def test_unknown_usage_in_previous_run_blocks_only_enabled_token_budget(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    e.run(max_attempts_now=0)
    e.ledger.event(e.run_id, 'accounting_unknown', reason='missing token receipt')
    later = engine_for(root)
    later.open_run(new_run=True)
    later.admit()  # Time is measured independently; tokens are unlimited.
    later.task.budget.max_tokens = 100
    with pytest.raises(OPCError, match='accounting incomplete'):
        later.admit()


def test_preparation_charges_task_without_creating_execution_run(make_project):
    from opc.core.ledger import Ledger
    root = make_project(tsk=task(budget={}))
    onboard(root, 'codex', task_id='t-toy', prior_tokens=4, prior_wall_seconds=2,
            record_usage_only=True)
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    assert ledger.runs() == []
    assert ledger.task_totals('t-toy')['tokens'] == 4
    onboard(root, 'codex', task_id='t-toy', prior_tokens=4, prior_wall_seconds=2,
            record_usage_only=True)
    assert ledger.task_totals('t-toy')['wall_seconds'] == 2
    assert ledger.task_totals('t-toy')['tokens'] == 4


def test_authorized_budget_extension_keeps_spent_usage(make_project, engine_for):
    root = make_project()
    onboard(root, 'codex', task_id='t-toy', max_tokens=10,
            prior_tokens=10, prior_wall_seconds=1, record_usage_only=True)
    e = engine_for(root)
    assert e.ledger.task_totals('t-toy')['tokens'] == 10
    # The existing Engine sees the explicit allowance without discarding consumption.
    onboard(root, 'codex', task_id='t-toy', max_tokens=20,
            prior_tokens=10, prior_wall_seconds=1, record_usage_only=True)
    assert e.budget_left()['tokens'] == 10


def test_null_local_budget_preserves_explicit_contract_limit(make_project, engine_for):
    t = task()
    t['budget']['max_tokens'] = 40
    root = make_project(tsk=t)
    settings(root, {'max_tokens': None, 'max_wall_seconds': None})
    e = engine_for(root)
    assert e.task.budget.max_tokens == 40
    assert e.task.budget.max_wall_seconds == 600


def test_exhausted_task_does_not_measure_new_baseline(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    e.run(max_attempts_now=0)
    e.ledger.charge(e.run_id, None, 'expert', Cost(601, 0, None))
    later = engine_for(root)
    result = later.run(new_run=True, max_attempts_now=0)
    assert result['state'] == 'closed'
    assert 'budget_exhausted' in result['stop_reason']
    assert result['champion'] is None


def test_preflight_is_charged_to_task_without_execution_run(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    assert e.preflight()['ok']
    assert e.ledger.runs() == []
    assert e.ledger.task_totals('t-toy')['wall_seconds'] > 0


def test_status_displays_preparation_budget_without_fake_run(make_project, capsys):
    from opc.cli import main
    root = make_project(tsk=task(budget={}))
    onboard(root, 'codex', task_id='t-toy', prior_tokens=4, prior_wall_seconds=2,
            record_usage_only=True)
    assert main(['status', '-p', str(root), '--task', 't-toy']) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]['run_id'] is None
    assert rows[0]['task'] == 't-toy'
    assert rows[0]['revision'] == 'r0001'
    assert rows[0]['budget']['used']['tokens'] == 4
    assert rows[0]['budget']['limits']['wall_seconds'] == 7200
    assert 'files' not in rows[0]['preparation'][0]


def test_profile_defaults_task_and_local_sources_are_frozen(make_project, engine_for):
    t = task(profile={'name': 'development', 'version': 2})
    del t['budget']['max_wall_seconds']
    root = make_project(tsk=t, extra={'.opc/profiles/development/v2.json': json.dumps({
        'name': 'development', 'version': 2,
        'budget': {'max_wall_seconds': 120},
        'workers': {'expert': {'model': 'profile-model', 'reasoning_effort': 'low'}}})})
    settings(root, {'max_wall_seconds': None})
    write(root / CONFIG_PATH, json.dumps({'budget': {'max_wall_seconds': None},
          'expert': {'model': 'local-model'}}))
    e = engine_for(root)
    e.open_run()
    assert e.task.budget.max_wall_seconds == 120
    frozen = json.loads((e.artifact_dir() / 'frozen/baseline.json').read_text())
    assert frozen['execution']['configuration_sources']['profile']['version'] == 2
    assert frozen['execution']['configuration_sources']['workers.expert.model'] == '.opc/local/workers.json'
    assert frozen['execution']['workers']['expert']['model'] == 'local-model'
    assert frozen['execution']['workers']['expert']['reasoning_effort'] == 'low'


def test_project_hard_limit_survives_null_and_budget_extension(make_project, engine_for):
    root = make_project(tsk=task(hard_limits={'max_tokens': 30}))
    project = root / '.opc/project.json'
    raw = json.loads(project.read_text())
    raw['hard_limits'] = {'max_tokens': 20, 'max_wall_seconds': 100}
    write(project, json.dumps(raw))
    from opc.tests.conftest import git
    git(root, 'add', '.opc/project.json')
    git(root, 'commit', '-qm', 'project hard limits')
    settings(root, {'max_tokens': None, 'max_wall_seconds': None})
    e = engine_for(root)
    e.open_run()
    scope = e.ledger.preparation_scope('t-toy')
    e.ledger.event(scope, 'task_budget_authorized', max_tokens=1000, max_wall_seconds=1000)
    assert e.effective_budget().max_tokens == 20
    assert e.effective_budget().max_wall_seconds == 100
    e.ledger.charge(e.run_id, None, 'expert', Cost(1, 21, 0))
    with pytest.raises(BudgetExhausted, match='max_tokens'):
        e.hard_check()


@pytest.mark.parametrize('profile,reason', [('tuning', 'objective'), ('exploration', 'materials')])
def test_profile_cannot_release_unimplemented_capabilities(make_project, engine_for, profile, reason):
    root = make_project(tsk=task(profile={'name': profile, 'version': 1}, acceptance={}))
    e = engine_for(root)
    with pytest.raises(OPCError, match=reason):
        e.run(max_attempts_now=1)
    assert not e.ledger.runs()


def test_inline_credentials_and_local_scope_overrides_are_rejected(make_project, engine_for):
    from opc.tests.conftest import component
    root = make_project(comp=component(env={'SERVICE_API_KEY': 'must-not-freeze'}))
    with pytest.raises(OPCError, match='credential.*inherit'):
        engine_for(root)
    path = root / '.opc/components/toy.json'
    raw = json.loads(path.read_text()); raw['env'] = {}
    write(path, json.dumps(raw))
    write(root / '.opc/local/bindings.json', json.dumps({'goal': 'replace task'}))
    with pytest.raises(OPCError, match='unknown field.*goal'):
        engine_for(root)
