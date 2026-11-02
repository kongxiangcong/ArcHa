"""One detached execution of an already accepted control request, never a scheduler."""
from __future__ import annotations

import argparse
from pathlib import Path

from ..core.engine import Engine
from ..core.ledger import Ledger


def execute(root, run_id, request_id):
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    engine = None
    phase = "读取原运行的保存配置"
    action = "恢复"
    try:
        record = ledger.db.execute('SELECT action FROM control_requests WHERE request_id=?', (request_id,)).fetchone()
        action = '停止' if record and record['action'] == 'stop' else '恢复'
        row = ledger.run(run_id)
        engine = Engine(root, row['task_id'], run_id=run_id, log=lambda _: None)
        phase = action + "原运行的工作"
        engine.run(control_request_id=request_id)
    except BaseException as error:
        reason = '项目已有运行端占用，未启动第二个执行者' if str(error).startswith('another controller holds ') else phase + '未完成，请检查保存配置或执行环境'
        ledger.event(run_id, 'control_execution_failed', request_id=request_id, phase=phase, error_type=type(error).__name__, error=str(error)[:1000])
        ledger.finish_control_request(request_id, 'failed', action + '失败；' + reason + '；原有工作与结果保留')
    finally:
        if engine:
            engine.ledger.close()
        ledger.close()


def main():
    parser = argparse.ArgumentParser(description='Execute an accepted local run request')
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--request-id', required=True)
    args = parser.parse_args()
    execute(args.project, args.run_id, args.request_id)


if __name__ == '__main__':
    main()
