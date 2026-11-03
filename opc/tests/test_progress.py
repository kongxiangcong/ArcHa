"""Narration follows processed facts; missing display text never changes execution."""
import json
from pathlib import Path

import pytest

from opc.adapters.worker import PLAN_SCHEMA, PROGRESS_RULE, designer_output
from opc.core.ledger import Ledger
from opc.core.model import Cost
from opc.observer.adapter import ObserverAdapter
from opc.observer.workbench import current_progress
from opc.tests.conftest import component, task
from opc.tests.test_research_loop import Sequence, plan, stop, use_sequence


def scene(root, run_id):
    adapter = ObserverAdapter(root)
    return adapter.workbench(adapter._id('run', run_id))['data']


def test_worker_observations_survive_processing_and_pause_with_true_next_step(make_project, engine_for):
    class Explains(Sequence):
        def implement(self, *args):
            call = super().implement(*args)
            call.output['progress_summary'] = '已实现参数调整，并完成本地检查。下一步检查计算结果。'
            return call
    root = make_project()
    worker = Explains([plan(1, progress_summary='已完成首轮方案分析。下一步实施参数调整。')], [4])
    engine = use_sequence(engine_for(root), worker)
    engine.run(max_attempts_now=1)
    progress = scene(root, engine.run_id)['current_progress']
    assert '已实现参数调整' in progress['progress_summary']
    assert '下一步等待用户恢复' in progress['progress_summary']
    assert '下一步检查计算结果' not in progress['progress_summary']
    assert scene(root, engine.run_id)['current_progress'] == progress
    designer = next(c for c in engine.ledger.calls(engine.run_id) if c['role'] == 'designer')
    assert json.loads(Path(designer['receipt_path']).read_text())['output']['progress_summary'].endswith('下一步检查计算结果。')
    assert 'progress_summary' not in engine.attempt_records()[0]['plan']


def test_rejected_plan_does_not_display_workers_claim_of_execution(make_project, engine_for):
    root = make_project()
    engine = engine_for(root)
    def corrected(ctx):
        progress = scene(root, engine.run_id)['current_progress']
        assert '交付清单' in progress['progress_summary']
        assert '尚未据此启动实施' in progress['progress_summary']
        assert '修正方案' in progress['progress_summary']
        assert '已经运行完成' not in progress['progress_summary']
        return plan(1)
    use_sequence(engine, Sequence([plan(1, deliverables=['tools'],
        progress_summary='测试已经运行完成。下一步交付。'), corrected], [4])).run(max_attempts_now=1)


def test_successful_designer_call_with_missing_output_does_not_become_success(make_project, engine_for):
    root = make_project(comp=component(scratch=['raw/**']))
    def inspect(ctx):
        progress = scene(root, engine.run_id)['current_progress']['progress_summary']
        assert '不能把调用返回视为工作成功' in progress
        assert '下一步由研究协调' in progress
        return stop(ctx)
    engine = use_sequence(engine_for(root), Sequence([plan(1, deliverables=['raw/missing.txt']), inspect], [4]))
    engine.run()
    assert engine.attempt_records()[0]['outcome'] == 'worker_failed'


@pytest.mark.parametrize('state,reason,expected', [
    ('paused', 'paused by user', '等待用户恢复'),
    ('blocked', 'expert decision: deliverables must be file paths', '先解决这一问题'),
    ('closed', 'budget_exhausted: max_tokens', '新的预算授权'),
])
def test_control_state_replaces_stale_next_step(make_project, engine_for, state, reason, expected):
    root = make_project()
    engine = use_sequence(engine_for(root), Sequence([plan(1)], [4]))
    engine.run(max_attempts_now=1)
    engine.ledger.set_run_state(engine.run_id, state, reason)
    progress = scene(root, engine.run_id)['current_progress']
    assert expected in progress['progress_summary']
    if state != 'paused':
        assert '下一步等待用户恢复' not in progress['progress_summary']


def test_latest_progress_uses_sequence_not_clock_and_ignores_generic_completions(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite3')
    ledger.event('preparation:one', 'preparation', state='pending', reason='toolchain missing')
    ledger.event('preparation:one', 'preparation', state='ready')
    ledger.event('preparation:one', 'worker_call', role='onboard', ok=True, worker_progress_summary='这不是已处理结果。下一步继续。')
    events = ledger.events('preparation:one')
    for index, event in enumerate(events):
        event['at'] = f'2026-01-0{3-index}'
        event['attempt_no'] = event['attempt']
    value = current_progress(events)
    assert value['sequence'] == events[1]['seq'] and '准备检查已通过' in value['progress_summary']
    assert current_progress([dict(seq=1, kind='worker_call', body={}, at=None)]) is None
    assert ledger.events('preparation:other') == []


def test_preparation_without_run_and_object_switch_remain_separate(tmp_path):
    from opc.tests.test_observer_preparation import fixture
    fixture(tmp_path)
    ledger = Ledger(tmp_path / '.opc/local/ledger.sqlite3')
    ledger.event('preparation:dma-backpressure', 'preparation_candidate',
                 worker_progress_summary='已接通本地编译工具并记录检查结果。下一步提交准备审核。')
    adapter = ObserverAdapter(tmp_path)
    task_view = next(t for t in adapter.overview()['data']['tasks'] if t['research_task_id'] == 'R01')
    ident = adapter.research_task(task_view['id'])['data']['runs'][0]['id']
    progress = adapter.workbench(ident)['data']['current_progress']
    assert progress['role'] == 'onboard' and '已接通本地编译工具' in progress['progress_summary']
    assert adapter.workbench(ident)['data']['kind'] == 'preparation'
    assert ledger.runs() == []
    assert ObserverAdapter(tmp_path).workbench(ident)['data']['current_progress'] == progress


@pytest.mark.parametrize('value', [None, '', [], {'bad': True}, '内部输出 tools/check.py。下一步查看。'])
def test_display_field_never_controls_dispatch_or_requires_retries(make_project, engine_for, value):
    root = make_project()
    worker = Sequence([plan(1, progress_summary=value)], [4])
    engine = use_sequence(engine_for(root), worker)
    engine.run(max_attempts_now=1)
    assert len(worker.contexts) == 1 and len(engine.attempt_records()) == 1
    assert not engine.ledger.events(engine.run_id, 'expert_rejected')
    assert 'tools/check.py' not in scene(root, engine.run_id)['current_progress']['progress_summary']


@pytest.mark.parametrize('accepted', [False, True])
def test_review_processed_and_final_delivery_are_distinct(make_project, engine_for, monkeypatch, accepted):
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[dict(id='R', text='check result', verification='review')]))
    engine = use_sequence(engine_for(root), Sequence([stop]))
    engine.run()
    def review(*args):
        return dict(ok=True, verdict='accept' if accepted else 'reject', summary='review', overreach=[],
                    progress_summary='已核对现有对照，仍需谨慎解释。下一步提交审核判断。',
                    requirement_findings=[dict(id='R', status='met' if accepted else 'not_met', evidence=['checked'], gap='')])
    monkeypatch.setattr('opc.core.promote.run_reviewer', review)
    report = promote(engine, review='codex')
    processed = engine.ledger.events(engine.run_id, 'review_processed')[-1]['body']
    assert processed['progress_source'] == 'reviewer' and '已核对现有对照' in processed['progress_summary']
    assert ('未通过' in processed['progress_summary']) is not accepted
    text = scene(root, engine.run_id)['current_progress']['progress_summary']
    assert report['complete'] is accepted
    assert ('本任务已完成，暂无后续执行安排' in text) is accepted
    assert '下一步' in text if not accepted else True


def test_new_protocol_is_strict_but_display_field_remains_optional_at_runtime():
    from opc.adapters.prompts import expert_prompt
    assert 'progress_summary' in PLAN_SCHEMA['required']
    assert set(PLAN_SCHEMA['required']) == set(PLAN_SCHEMA['properties'])
    assert 'progress_summary' not in PLAN_SCHEMA['properties']['works']['items']['properties']
    assert PROGRESS_RULE in expert_prompt({})
    assert designer_output('{"summary":"legacy"}') == {'summary': 'legacy'}
    assert designer_output('{"summary":"ok","progress_summary":"说明"}')['progress_summary'] == '说明'


@pytest.mark.parametrize('finish', ['request_acceptance', 'close_incomplete'])
def test_analysis_only_and_closeout_keep_worker_observations_but_engine_next_step(make_project, engine_for, finish):
    root = make_project()
    engine = engine_for(root)
    def close(ctx):
        analysis = scene(root, engine.run_id)['current_progress']
        assert analysis['role'] == 'expert'
        assert '已核对现有对照' in analysis['progress_summary'] and '没有新增实施工作' in analysis['progress_summary']
        return dict(finish=finish, stop_reason='结束本轮分析', gaps=['缺少恢复路径的对照'],
                    reopen_conditions=['恢复测试条件可用并获得继续授权'],
                    progress_summary='已核对目前已有的研究证据。下一步应由引擎处理收尾请求。')
    use_sequence(engine, Sequence([dict(select_work=False,
        progress_summary='已核对现有对照，证据仍有缺口。下一步交由研究协调判断。'), close])).run()
    value = scene(root, engine.run_id)['current_progress']['progress_summary']
    assert '已核对目前已有的研究证据' in value
    if finish == 'request_acceptance':
        assert '尚待检查' in value and '下一步按合同' in value
    else:
        assert '缺少恢复路径的对照' in value
        assert '恢复测试条件可用并获得继续授权' in value and '任务尚未完成' in value
    assert engine.attempt_records() == []


@pytest.mark.parametrize('backend', ['codex', 'dsh'])
@pytest.mark.parametrize('accepted', [True, False])
def test_onboard_and_preparation_review_narration_use_real_preparation_scope(make_project, monkeypatch, backend, accepted):
    from opc.adapters.worker import WorkerCall
    from opc.scaffold.onboard import onboard
    root = make_project(tsk=task(acceptance={}, requirements=[], preparation_review=True))
    calls = []
    def run(self, role, prompt, tree, log, mode, schema):
        calls.append(role)
        assert 'progress_summary' in prompt
        assert set(schema['required']) == set(schema['properties'])
        log.mkdir(parents=True, exist_ok=True)
        if role == 'onboard':
            evidence = log / 'checks.txt'
            evidence.write_text('observed positive and negative controls')
            reply = dict(state='ready', reason='checks recorded', evidence=[evidence.relative_to(root).as_posix()],
                         progress_summary='已完成工具接入与正反对照检查。下一步提交独立准备审核。')
        else:
            reply = dict(verdict='accept' if accepted else 'reject', reason='checked controls',
                         progress_summary='已独立核对准备检查的正反对照。下一步交由引擎处理审核意见。')
        return WorkerCall(role, True, Cost(1, 7, None), extra={'usage_complete': True}), json.dumps(reply)
    target = 'opc.adapters.codex.CodexWorker._run' if backend == 'codex' else 'opc.adapters.dsh.DshWorker._run'
    monkeypatch.setattr(target, run)
    result = onboard(root, backend, task_id='t-toy')
    assert result['ok'] is accepted and calls == ['onboard', 'reviewer']
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    scope = ledger.preparation_scope('t-toy')
    assert not ledger.runs()
    assert '已完成工具接入' in ledger.events(scope, 'preparation_candidate')[-1]['body']['progress_summary']
    assert ledger.events(scope, 'review_processed')[-1]['body']['progress_source'] == 'reviewer'
    value = scene(root, scope)
    assert value['kind'] == 'preparation'
    assert '已独立核对准备检查' in value['current_progress']['progress_summary']
    assert ('审核未通过' in value['current_progress']['progress_summary']) is not accepted
