"""Bounded work handoffs through the ordinary Engine start/control/resume seam."""
import json
import threading
import time

import pytest

from opc.adapters.worker import WorkerCall
from opc.core.model import Cost
from opc.tests.test_research_loop import plan, stop, use_sequence
from opc.tests.conftest import git


class Branches:
    def __init__(self, works, overlap=None):
        self.works = works
        self.calls = 0
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.parents = []
        self.trees = []
        self.overlap = overlap
        self.entered = threading.Event()
        if overlap is None:
            self.entered.set()

    def propose(self, ctx, tree, log_dir):
        self.calls += 1
        output = {'works': self.works} if self.calls == 1 or ctx.get('decision_correction') else stop(ctx)
        return WorkerCall('expert', True, Cost(), output=output, exhausted=output.get('exhausted', False))

    def implement(self, work, ctx, tree, log_dir):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.trees.append(str(tree))
            self.parents.append(git(tree, 'rev-parse', 'HEAD').strip())
            if self.overlap is not None and self.active >= self.overlap:
                self.entered.set()
        assert self.entered.wait(3), 'configured ready workers did not overlap'
        time.sleep(.02)
        (tree / 'params.json').write_text(json.dumps({'x': 4}))
        with self.lock:
            self.active -= 1
        return WorkerCall('designer', True, Cost(.08, 11, 0.0), output={'summary': 'Independent branch checked'})


@pytest.mark.parametrize('limit', [None, 2])
def test_selected_branches_use_bounded_parallel_fixed_inputs(make_project, engine_for, limit):
    root = make_project()
    if limit:
        (root / '.opc/local').mkdir(exist_ok=True)
        (root / '.opc/local/workers.json').write_text(json.dumps({'max_concurrency': limit}))
    worker = Branches([plan(i, work_id=f'branch-{i}', evaluate=False) for i in range(5)], overlap=limit or 3)
    e = use_sequence(engine_for(root), worker)
    result = e.run()
    assert result['state'] == 'closed' and result['pending_conclusions'] == []
    assert len(e.attempt_records()) == 5 and worker.calls == 2
    assert worker.peak == (limit or 3)
    assert len(set(worker.trees)) == 5 and set(worker.parents) == {result['baseline']}
    assert result['spent']['tokens'] == 55
    assert result['spent']['wall_seconds'] >= .4
    assert result['max_concurrency'] == (limit or 3)


@pytest.mark.parametrize('case', ['cycle', 'unknown', 'missing_artifact'])
def test_dependencies_are_validated_and_wait_for_actual_artifacts(make_project, engine_for, case):
    a = plan(1, work_id='a', evaluate=False)
    b = plan(2, work_id='b', evaluate=False, dependencies=[{'work_id': 'a', 'artifact': 'missing.txt'}])
    if case == 'cycle':
        a['dependencies'] = [{'work_id': 'b', 'artifact': 'candidate'}]
    if case == 'unknown':
        b['dependencies'][0]['work_id'] = 'unknown'
    worker = Branches([a, b])
    e = use_sequence(engine_for(make_project()), worker)
    result = e.run()
    assert result['state'] == 'blocked'
    if case == 'missing_artifact':
        assert len(worker.trees) == 1 and e.attempt_records()[0]['candidate']
        assert e.attempt_records()[1]['outcome'] is None
        assert result['dag'][1]['blocked_by'] == ['a:missing.txt']
    else:
        assert e.attempt_records() == [] and worker.trees == []
        assert case in result['stop_reason']


def test_dependency_uses_saved_unaccepted_candidate_and_declared_artifact(make_project, engine_for):
    from opc.tests.conftest import component
    class Produces(Branches):
        def implement(self, work, ctx, tree, log_dir):
            if work['work_id'] == 'producer':
                (tree / 'scratch').mkdir()
                (tree / 'scratch/measurement.json').write_text('{"observed": 17}')
            else:
                entry = ctx['handoff']['inputs'][1]
                assert json.loads(__import__('pathlib').Path(entry['path']).read_text()) == {'observed': 17}
            return super().implement(work, ctx, tree, log_dir)
    worker = Produces([plan(1, work_id='producer', evaluate=False, deliverables=['scratch/measurement.json']),
        plan(2, work_id='consumer', evaluate=False, base_work_id='producer', directions=['code', 'measurement'],
             dependencies=[{'work_id': 'producer', 'artifact': 'candidate'},
                           {'work_id': 'producer', 'artifact': 'outputs/scratch/measurement.json'}])])
    e = use_sequence(engine_for(make_project(comp=component(scratch=['scratch/**']))), worker)
    result = e.run()
    assert result['state'] == 'closed'
    first, second = e.attempt_records()
    assert first['outcome'] == 'work' and result['champion'] == result['baseline']
    assert second['parent'] == first['candidate'] == worker.parents[1]
    assert result['dag'][1]['directions'] == ['code', 'measurement']
    assert (e.attempt_dir(1) / 'outputs/scratch/measurement.json').read_text() == '{"observed": 17}'


def test_failed_branch_does_not_block_independent_work(make_project, engine_for):
    class Fails(Branches):
        def implement(self, work, ctx, tree, log_dir):
            if work['work_id'] == 'failed':
                return WorkerCall('designer', False, Cost(.01, 3, 0), error='local check failed')
            return super().implement(work, ctx, tree, log_dir)
    worker = Fails([plan(1, work_id='failed', evaluate=False), plan(2, work_id='independent', evaluate=False),
                   plan(3, work_id='waiting', evaluate=False, dependencies=[{'work_id': 'failed', 'artifact': 'candidate'}])])
    e = use_sequence(engine_for(make_project()), worker)
    result = e.run()
    assert result['state'] == 'blocked'
    assert [a['outcome'] for a in e.attempt_records()] == ['worker_failed', 'work', None]
    assert result['dag'][2]['blocked_by'] == ['failed:candidate']


def test_formal_measurement_waits_for_all_controlled_compute(make_project, engine_for, monkeypatch):
    from opc.domains.command import CommandDomain
    worker = Branches([plan(i, work_id=f'work-{i}', evaluate=i % 2 == 0) for i in range(5)], overlap=3)
    e = use_sequence(engine_for(make_project()), worker)
    original = CommandDomain.evaluate
    samples = []
    def evaluate(self, tree, out, repeats, **kwargs):
        if 'attempts' in str(out):
            samples.append(worker.active)
            assert worker.active == 0
        return original(self, tree, out, repeats, **kwargs)
    monkeypatch.setattr(CommandDomain, 'evaluate', evaluate)
    result = e.run()
    assert result['state'] == 'closed' and samples == [0, 0, 0]
    assert len({a['parent'] for a in e.attempt_records()}) == 1
    assert result['champion_metrics']['loss'] == 10


class Processes(Branches):
    def __init__(self, works, seconds, *, expected_processes=3, startup_delay=0):
        super().__init__(works)
        self.seconds = seconds
        self.expected_processes = expected_processes
        self.startup_delay = startup_delay
        self.processes_started = 0
        self.started = threading.Event()
        self.executed = []

    def implement(self, work, ctx, tree, log_dir):
        import subprocess
        import sys
        from opc.core.platform import Process
        started = time.monotonic()
        with self.lock:
            self.executed.append(work['work_id'])
        (tree / 'params.json').write_text('{"x":4}')
        time.sleep(self.startup_delay)  # Optional slow-start injection, not a readiness assertion.
        with Process([sys.executable, '-c', f'import time; time.sleep({self.seconds})'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
            with self.lock:
                self.processes_started += 1
                if self.processes_started == self.expected_processes:
                    self.started.set()  # OS process and its ownership are now established.
            process.wait()
        return WorkerCall('designer', process.returncode == 0,
                          Cost(time.monotonic() - started, 0, 0), output={'summary': 'Controlled computation ended'})


@pytest.mark.parametrize('command', ['pause', 'stop'])
def test_parallel_control_drains_receipts_and_never_dispatches_followup(make_project, engine_for, command):
    from opc.core.ledger import Ledger
    worker = Processes([plan(i, work_id=f'work-{i}', evaluate=True) for i in range(4)], 2 if command == 'pause' else 20)
    e = use_sequence(engine_for(make_project()), worker)
    def control():
        assert worker.started.wait(30)
        external = Ledger(e.ledger.path)
        external.set_control(e.run_id, command)
        external.close()
    sender = threading.Thread(target=control)
    sender.start()
    result = e.run()
    sender.join(timeout=3)
    assert not sender.is_alive()
    assert result['state'] == ('paused' if command == 'pause' else 'closed')
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'designer']
    assert len(calls) == 3 and all(c['result'] is not None for c in calls)
    assert worker.calls == 1 and len(worker.executed) == 3
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'evaluator']) == 1
    assert all(__import__('pathlib').Path(c['input']['tree']).exists() for c in calls)
    if command == 'pause':
        result = e.run()
        assert result['state'] == 'closed' and result['pending_conclusions'] == []
        assert sorted(worker.executed) == ['work-0', 'work-1', 'work-2', 'work-3']
    else:
        assert all(c['state'] == 'cancelled' for c in calls)
        assert e.run()['run_id'] == result['run_id'] and len(worker.executed) == 3


def test_parallel_wall_allowance_cancels_on_sum_of_active_execution(make_project, engine_for):
    from opc.tests.conftest import task
    contract = task()
    contract['budget']['max_wall_seconds'] = 6
    worker = Processes([plan(i, work_id=f'work-{i}', evaluate=False) for i in range(3)], 20)
    e = use_sequence(engine_for(make_project(tsk=contract)), worker)
    result = e.run()
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'designer']
    assert result['state'] == 'closed' and 'budget_exhausted' in result['stop_reason']
    assert len(calls) == 3 and all(c['state'] == 'cancelled' for c in calls)
    assert all(c['result']['cost']['wall_seconds'] < 6 for c in calls)
    assert result['spent']['wall_seconds'] >= 6
    assert not result['pending_conclusions']  # cancelled work is still unfinished, not fake success.


@pytest.mark.parametrize('failure', ['designer', 'designer_infra', 'evaluation'])
def test_branch_failure_does_not_starve_independent_work_beyond_cap(make_project, engine_for, monkeypatch, failure):
    from opc.domains.command import CommandDomain
    from opc.domain import Evaluation
    from opc.core.model import Outcome
    class Fails(Branches):
        def implement(self, work, ctx, tree, log_dir):
            if failure in ('designer', 'designer_infra') and work['work_id'] == 'bad':
                return WorkerCall('designer', False, Cost(.01, 0, 0), error='local check failed',
                                  extra={'infra': failure == 'designer_infra'})
            return super().implement(work, ctx, tree, log_dir)
    worker = Fails([plan(0, work_id='bad', evaluate=failure == 'evaluation')] +
                   [plan(i, work_id=f'independent-{i}', evaluate=False) for i in range(4)])
    root = make_project()
    (root / '.opc/local').mkdir(exist_ok=True)
    (root / '.opc/local/workers.json').write_text('{"max_concurrency":2}')
    e = use_sequence(engine_for(root), worker)
    original = CommandDomain.evaluate
    def evaluate(self, tree, out, repeats, **kwargs):
        if 'a000001' in str(out):
            return Evaluation([], failure=Outcome.INFRA, reason='timing runner unavailable')
        return original(self, tree, out, repeats, **kwargs)
    monkeypatch.setattr(CommandDomain, 'evaluate', evaluate)
    result = e.run()
    assert all(a['outcome'] == 'work' for a in e.attempt_records()[1:])
    assert len(e.attempt_records()) == 5
    if failure in ('evaluation', 'designer_infra'):
        assert result['state'] == 'blocked' and e.attempt_records()[0]['outcome'] is None
    else:
        assert result['state'] == 'closed' and e.attempt_records()[0]['outcome'] == 'worker_failed'


@pytest.mark.parametrize('startup_delay', [0, .1])
def test_unknown_execution_cancels_peers_and_blocks_new_run(make_project, engine_for, startup_delay):
    from opc.core.model import OPCError
    class Unknown(Processes):
        def implement(self, work, ctx, tree, log_dir):
            if work['work_id'] == 'unknown':
                with self.lock:
                    self.executed.append(work['work_id'])
                assert self.started.wait(30)
                raise RuntimeError('terminal lost')
            return super().implement(work, ctx, tree, log_dir)
    worker = Unknown([plan(0, work_id='unknown', evaluate=False),
                      plan(1, work_id='peer-1', evaluate=False), plan(2, work_id='peer-2', evaluate=False)],
                     20, expected_processes=2, startup_delay=startup_delay)
    root = make_project()
    e = use_sequence(engine_for(root), worker)
    before = time.monotonic()
    with pytest.raises(RuntimeError, match='terminal lost'):
        e.run()
    assert time.monotonic() - before < 15
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'designer']
    assert len(calls) == 3 and calls[0]['result'] is None
    assert all(c['state'] == 'cancelled' for c in calls[1:])
    assert e.ledger.control(e.run_id) == 'run'
    assert all(__import__('pathlib').Path(c['input']['tree']).exists() for c in calls)
    later = engine_for(root)
    with pytest.raises(OPCError, match='execution unknown'):
        later.run(new_run=True)
    assert len(later.ledger.runs()) == 1


@pytest.mark.parametrize('cap', ['session', 'budget'])
def test_parallel_selection_respects_per_node_execution_caps(make_project, engine_for, cap):
    from opc.tests.conftest import task
    contract = task()
    if cap == 'budget':
        contract['budget']['max_attempts'] = 1
    worker = Branches([plan(i, work_id=f'node-{i}', evaluate=False) for i in range(4)])
    e = use_sequence(engine_for(make_project(tsk=contract)), worker)
    result = e.run(max_attempts_now=1 if cap == 'session' else None)
    assert len(worker.trees) == 1 and len(e.attempt_records()) == 4
    assert result['state'] == ('paused' if cap == 'session' else 'closed')
    assert [a['outcome'] for a in e.attempt_records()] == ['work', None, None, None]
    assert worker.calls == 1
    if cap == 'budget':
        assert result['spent']['search_attempts'] == 1 and 'max_attempts' in result['stop_reason']
    else:
        result = e.run(max_attempts_now=0)
        assert len(worker.trees) == 4 and worker.calls == 1
        assert result['state'] == 'paused'


def test_concurrency_is_frozen_across_resume_and_observer_shows_dependencies(make_project, engine_for):
    from opc.observer.adapter import ObserverAdapter
    root = make_project()
    (root / '.opc/local').mkdir(exist_ok=True)
    config = root / '.opc/local/workers.json'
    config.write_text('{"max_concurrency":2}')
    worker = Branches([plan(i, work_id=f'node-{i}', evaluate=False) for i in range(4)])
    first = use_sequence(engine_for(root), worker)
    result = first.run(max_attempts_now=1)
    worker.overlap = 2
    worker.entered.clear()
    config.write_text('{"max_concurrency":1}')
    resumed = use_sequence(engine_for(root), worker)
    result = resumed.run(max_attempts_now=0)
    assert result['run_id'] == first.run_id and result['max_concurrency'] == worker.peak == 2
    observer = ObserverAdapter(root)
    ref = next(r for r in observer.overview()['data']['unlinked_runs'] if r['source_run_id'] == first.run_id)
    observed = observer.run(ref['id'])['data']
    assert observed['max_concurrency'] == 2
    assert observed['configuration_sources']['max_concurrency'] == '.opc/local/workers.json'
    attempt = observer.attempt(ref['id'], 1)['data']
    assert attempt['work_id'] == 'node-0' and attempt['dependencies'] == []


@pytest.mark.parametrize('value', [0, -1, True, '3'])
def test_concurrency_rejects_invalid_external_configuration(make_project, engine_for, value):
    from opc.core.model import OPCError
    root = make_project()
    (root / '.opc/local').mkdir(exist_ok=True)
    (root / '.opc/local/workers.json').write_text(json.dumps({'max_concurrency': value}))
    with pytest.raises(OPCError, match='max_concurrency'):
        engine_for(root)


@pytest.mark.parametrize('after_registration', [False, True])
def test_saved_batch_decision_materializes_once_after_restart(make_project, engine_for, monkeypatch, after_registration):
    worker = Branches([plan(i, work_id=f'node-{i}', evaluate=False) for i in range(3)])
    root = make_project()
    e = use_sequence(engine_for(root), worker)
    original = e.ledger.begin_selected_works
    def interrupted(*args, **kwargs):
        if after_registration:
            original(*args, **kwargs)
        raise RuntimeError('batch handoff interrupted')
    monkeypatch.setattr(e.ledger, 'begin_selected_works', interrupted)
    with pytest.raises(RuntimeError, match='batch handoff interrupted'):
        e.run()
    before = e.ledger.totals(e.run_id)
    assert worker.calls == 1 and worker.trees == []
    resumed = use_sequence(engine_for(root), worker)
    result = resumed.run(max_attempts_now=3)
    assert result['state'] == 'paused' and len(resumed.attempt_records()) == 3
    assert worker.calls == 1 and len(worker.trees) == 3
    assert len(resumed.ledger.events(resumed.run_id, 'work_selected')) == 3
    assert len([c for c in resumed.ledger.calls(resumed.run_id) if c['role'] == 'expert']) == 1
    assert resumed.ledger.totals(resumed.run_id)['tokens'] - before['tokens'] == 33
