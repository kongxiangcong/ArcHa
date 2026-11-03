"""Display-only narration attached to existing business events, never control input."""
from __future__ import annotations

import json
import re


def public_text(value):
    """Do not turn logs, identifiers or artifact references into user narration."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if (len(value) > 1200 or not re.search(r'[\u4e00-\u9fff]', value)
            or re.search(r'[/\\{}<>`]|\b[0-9a-f]{8,}\b|\w+_\w+|\S+\.(?:json|jsonl|py|md|txt)\b', value, re.I)):
        return None
    return value


def compose(actual, next_step, worker=None):
    # The worker supplies concrete observations. The engine owns the current next step.
    value = public_text(worker)
    detail = value.split('下一步', 1)[0].strip() if value and '下一步' in value else None
    if detail and not re.search(r'(?<!不代表)任务已完成|(?<!不代表)任务完成|(?<!未)验收通过', detail):
        actual = detail.rstrip('。；\n ') + '。' + actual
    return actual + next_step


def problem(reason):
    value = str(reason or '').lower()
    for keys, message in (
        (('deliverable',), '交付清单没有满足具体文件路径要求'),
        (('json', 'structured', 'reply is not', 'plan.'), '返回内容无法按工作协议读取'),
        (('scope violation', 'non-editable', 'sandbox'), '操作超出了允许修改的范围'),
        (('toolchain', 'compiler', 'command not found'), '所需工具链尚不可用'),
        (('accounting', 'usage',), '累计资源用量尚未确认'),
        (('pending feedback',), '已有工作结果尚未完成反馈分析'),
        (('review rejected', 'reviewer rejected'), '独立审核未通过，现有检查还不足以确认就绪'),
        (('execution unknown', 'termination unconfirmed'), '已有执行的结束情况尚未确认'),
    ):
        if any(key in value for key in keys):
            return message
    return '当前工作未满足继续推进的检查条件'


def decorate(db, scope, kind, attempt, body):
    """Enrich significant, already-recorded outcomes in the same transaction."""
    role, message = 'engine', None
    call_id = body.get('call_id')

    def previous(event_kind, no=attempt):
        row = db.execute('SELECT body FROM events WHERE run_id=? AND kind=? '
                         'AND attempt_no IS ? ORDER BY seq DESC LIMIT 1', (scope, event_kind, no)).fetchone()
        return json.loads(row[0]) if row else {}

    def last_progress():
        row = db.execute("SELECT body FROM events WHERE run_id=? AND body LIKE ? "
                         "AND kind NOT LIKE 'run_%' AND kind NOT LIKE 'control_%' ORDER BY seq DESC LIMIT 1",
                         (scope, '%"progress_source"%')).fetchone()
        return json.loads(row[0]).get('progress_summary') if row else None

    if kind == 'expert_decision' and body.get('output', {}).get('select_work') is False:
        role = 'expert'
        message = compose('本次已记录反馈分析，没有新增实施工作。',
                          '下一步由研究协调分析结果并确定方案。', body['output'].get('progress_summary'))
    elif kind == 'work_selected':
        decision = previous('expert_decision', None)
        role, call_id = 'expert', body.get('decision_call')
        message = compose('本轮方案已通过检查，尚未开始实施。',
                          '下一步按已确认方案开展实施或测量。', decision.get('output', {}).get('progress_summary'))
    elif kind in ('expert_rejected', 'expert_conflict'):
        correction = body.get('correctable') and body.get('correction_attempt', 0) < 2
        message = compose(problem(body.get('reason')) + '，本轮决策未被采用，尚未据此启动实施。',
                          '下一步修正方案，再提交引擎检查。' if correction else
                          '下一步先解决决策检查中的问题，再恢复推进。')
    elif kind == 'candidate_saved':
        execution = previous('execution')
        role, call_id = 'designer', execution.get('call_id')
        evaluation = body.get('evaluation_requested')
        message = compose('实施产出已通过范围检查并保留，正式评价结论尚未形成。' if evaluation is not False else
                          '实施产出已通过范围检查并保留，本轮未请求正式评价。',
                          '下一步按本轮方案开展正式评价。' if evaluation is True else
                          '下一步由研究协调分析结果并确定方案。', execution.get('progress_summary'))
    elif kind == 'experiment' and body.get('status') in ('completed', 'failed'):
        message = compose('正式检查未能完成，当前还不能据此判断方案收益。' if body['status'] == 'failed' else
                          '本轮正式检查已完成，能否用于可靠比较还需核对评价条件。',
                          '下一步先处理检查中的问题。' if body['status'] == 'failed' else '下一步核对可比性并处理评价结果。')
    elif kind == 'attempt_decided':
        outcome = body.get('outcome')
        actual = {
            'improvement': '本轮检查与比较支持数值改善，已更新当前最佳候选；这不代表任务已完成。',
            'no_gain': '本轮已完成评价，但没有得到满足接纳条件的数值收益。',
            'incomparable': '本轮已有观测，但评价条件不具备可靠可比性，目前不能判断性能收益。',
            'work': '本轮工作已保留，尚需研究协调结合结果判断后续安排。',
            'broken': '本轮正式检查未通过，当前候选不能视为可用结果。',
            'sandbox_violation': '实施触及了授权范围之外的内容，当前候选未被接纳。',
            'worker_failed': '本轮实施未满足交付检查，不能把调用返回视为工作成功。',
            'infra': '本轮所需执行条件出现问题，尚不能据此判断研究方案。',
            'abandoned': '本轮执行未完成，当前没有可确认的新结果。',
        }.get(outcome, '本轮工作处理已结束，结果仍需反馈分析。')
        message = compose(actual, '下一步由研究协调分析结果并确定方案。',
                          previous('execution').get('progress_summary') if outcome in ('work', 'improvement', 'no_gain', 'incomparable') else None)
    elif kind == 'expert_stop':
        role = 'expert'
        worker = previous('expert_decision', None).get('output', {}).get('progress_summary')
        if body.get('finish') == 'request_acceptance':
            message = compose('研究协调已选择交付候选并请求验收，任务是否完成尚待检查。',
                              '下一步按合同执行交付检查及所需独立审核。', worker)
        else:
            gaps = public_text('；'.join(v for v in body.get('gaps', []) if isinstance(v, str)))
            conditions = public_text('；'.join(v for v in body.get('reopen_conditions', []) if isinstance(v, str)))
            message = compose('本轮研究已收尾，任务尚未完成。' + ('剩余缺口：' + gaps + '。' if gaps else '剩余缺口尚需确认。'),
                              '下一步需满足恢复条件后再由用户决定是否继续：' + conditions + '。' if conditions else
                              '下一步先确认剩余缺口与可行的恢复条件，再由用户决定是否继续。', worker)
    elif kind == 'preparation_candidate':
        role = 'onboard'
        message = compose('研究准备产物及必要检查已记录，尚未启动正式研究。',
                          '下一步核对准备结果及所需独立审核。', body.get('worker_progress_summary'))
    elif kind == 'preparation':
        state = body.get('state')
        actual, following = {
            'ready': ('研究准备检查已通过，尚未启动正式研究。', '下一步提交准备结果并完成执行前检查，得到授权后再启动研究。'),
            'external_blocked': ('研究准备遇到尚未具备的外部执行条件。', '下一步先解决已确认的外部前提，再继续准备。'),
            'budget_exhausted': ('研究准备已达到本轮预算上限，本轮停止。', '下一步继续执行需要新的预算授权。'),
            'accounting_unknown': ('研究准备的累计资源用量尚未确认，当前不能继续派发。', '下一步先核对累计用量与预算，再决定是否继续。'),
        }.get(state, (problem(body.get('reason')) + '，准备尚未就绪。', '下一步先修正准备中的问题，再重新检查。'))
        message = compose(actual, following, body.get('worker_progress_summary'))
    elif kind == 'review_processed':
        role = 'reviewer'
        accepted = body.get('accepted') is True
        preparation = body.get('phase') == 'preparation'
        message = compose(('独立审核已通过，准备结果仍需引擎核对。' if preparation else
                           '独立审核已通过，但最终交付仍需引擎核对全部条件。') if accepted else
                          '独立审核未通过或未形成可用判断，当前不能据此确认完成。',
                          ('下一步由引擎核对准备结果，尚不启动正式研究。' if preparation else
                           '下一步由引擎核对最终交付条件。') if accepted else
                          ('下一步根据审核意见修正准备结果，再重新检查。' if preparation else
                           '下一步由研究协调根据审核意见确定补充验证方案。'),
                          body.get('worker_progress_summary') if body.get('ok') else None)
    elif kind == 'promotion_report':
        if body.get('complete'):
            message = '交付检查及合同要求的审核已经通过。本任务已完成，暂无后续执行安排。'
        else:
            action = body.get('next_action')
            following = {'retry_review': '下一步先解决审核条件，再重新审核。',
                         'retry_evaluation': '下一步先解决评价条件，再重新检查。',
                         'repair_candidate': '下一步根据交付缺口修正候选，再重新验收。',
                         'supplement_evidence': '下一步由研究协调根据交付缺口安排补充验证。',
                         'revise_standard': '下一步先由用户确认任务完成条件，再决定后续工作。'}.get(action,
                         '下一步由研究协调分析交付缺口并确定补充方案。')
            actual = {'retry_review': '独立审核尚未形成可用判断，任务尚未完成。',
                      'retry_evaluation': '交付评价尚未形成可用结果，任务尚未完成。',
                      'supplement_evidence': '交付仍缺少必需的验证证据，任务尚未完成。',
                      'revise_standard': '任务完成条件仍需确认，目前不能声明完成。'}.get(action,
                      '本轮交付检查发现候选仍需修正，任务尚未完成。')
            message = compose(actual, following, body.get('worker_progress_summary'))
    elif kind == 'delivery_evaluated':
        message = compose('交付所需的自动检查未满足要求，当前不能确认完成。' if body.get('failed') else
                          '交付所需的自动检查结果已核对，最终完成状态仍待确认。',
                          '下一步完成合同要求的独立审核，再核对交付缺口。' if body.get('review_next') else
                          '下一步由引擎汇总交付条件和缺口，记录最终交付结果。')
    elif kind in ('run_paused', 'run_blocked', 'run_closed'):
        reason = body.get('stop_reason') or ''
        if kind == 'run_paused':
            message = compose('本轮推进已暂停，已有结果保留。', '下一步等待用户恢复。', last_progress())
        elif reason.startswith('budget_exhausted'):
            message = compose('本轮已达到预算上限，执行已停止。', '下一步继续执行需要新的预算授权。', last_progress())
        elif kind == 'run_blocked':
            message = compose(problem(reason) + '，本轮推进已阻塞。', '下一步先解决这一问题，再由用户恢复运行。', last_progress())
        elif reason.startswith(('expert_exhausted', 'acceptance_requested')):
            return body  # expert_stop has the specific gaps and grounded next step.
        else:
            message = compose('本轮推进已停止，停止不代表任务已完成。',
                              '下一步需由用户确认是否继续及相应执行条件。', last_progress())
    elif kind == 'run_active':
        # Explicit resume invalidates a paused next step, but says nothing has executed.
        row = db.execute("SELECT kind FROM events WHERE run_id=? AND kind IN ('run_paused','run_blocked','run_active') ORDER BY seq DESC LIMIT 1", (scope,)).fetchone()
        if row and row[0] in ('run_paused', 'run_blocked'):
            message = '运行已恢复，已有结果保留，尚不能据此确认新增工作已完成。下一步由引擎接续未完成工作。'
    elif kind in ('control_pause', 'control_stop'):
        message = ('已收到暂停请求，正在等待在途工作收尾。下一步等待暂停确认，之后需由用户恢复。' if kind == 'control_pause' else
                   '已收到停止请求，已有结果将保留；停止不代表完成。下一步确认在途执行已结束，再由用户决定后续安排。')
    if message:
        body = dict(body, progress_summary=message, progress_source=role)
        if call_id:
            body['progress_call_id'] = call_id
    return body
