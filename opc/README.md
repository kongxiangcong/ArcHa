# opc：专题研究引擎

安装及工作台启动见 [仓库入口](../README.md)。本地部署入口 `python PROJECT/.archa/archa.py` 与安装后的 `opc` 使用同一 CLI。

所有命令都要求 `-p PROJECT --topic SLUG`：

| 命令 | 行为 |
| --- | --- |
| `init [--goal TEXT 或 --goal-file PATH] [--max-rounds N] [--template default或pim]` | 初始化专题，不覆盖已有目标、状态或配置；空目标不能运行 |
| `check` | 只读校验 Worker 配置 |
| `step` | 执行一次 Expert、Executor 或收尾调用 |
| `run` | 执行到领域终态或调用失败 |
| `stop` | 停止当前调用并等待归属进程结束 |
| `resume [--add-rounds N]` | 恢复提交，显式解除已处理阻塞，按需追加预算并继续 |
| `status` | 只读查看状态、轮数、下一动作、当前执行和错误 |
| `report` | 从已有材料生成专题内 `PROGRESS_LOG.md`，不调用 Worker |

退出码：一般成功为 0，输入或执行错误为 2；`run`/`resume` 分别以 0、3、4、5 表示 `COMPLETED`、`IN_PROGRESS`、`BLOCKED`、`BUDGET_EXHAUSTED`。预算耗尽不是调用失败，也不表示目标已完成。

工程 `.archa/workers.json` 优先；缺省使用 [分发配置](scaffold/workers.json)。角色为 `expert`、`executor`，可选显式 preset 或命令数组。例如自定义 Executor：

```json
{
  "roles": {
    "expert": {"preset": "codex", "model": "gpt-6.1-sol", "reasoning_effort": "medium"},
    "executor": {
      "command": ["python", "investigate.py", "{prompt_file}"],
      "input_mode": "file", "output_mode": "stdout", "timeout_seconds": 300
    }
  }
}
```

Expert 必须使用文件输出。Executor 可使用文件或纯 stdout 正文；stderr 只进入日志。非零退出、超时或空输出均不发布结果。命令不隐式经过 shell。可用变量、提交协议与状态约束以 [开发方案](../archa-refactor-plan.md) 为准。

运行模块职责：`core/engine.py` 调度与预算，`core/workspace.py` 状态及成果发布，`core/topic_control.py` 工程执行身份与停止，`adapters/worker.py` 通用配置和调用，`adapters/prompts.py` 角色上下文，`log.py` 按需报告。OS 进程树与独占锁由 `core/platform.py` 和 `core/windows.py` 提供。

历史数据不迁移；旧契约、Run、账本、Reviewer、晋升、工具拦截及暂停接口已退役。研究完成不意味着独立审核通过、合并或发布。
