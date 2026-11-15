---
name: archa-loop
description: 启动、停止或继续专题探索，按用户授权追加探索轮数并解释当前研究状态。
---

1. 确认目标工程与专题。明确目标可通过 archa-map 的初始化入口直接建立专题后运行，无需先调用 archa-task。
2. 使用 `python PROJECT/.archa/archa.py status -p PROJECT --topic SLUG` 阅读当前状态、已完成轮数及下一动作。
3. 按请求调用同一本地入口的 `run`、`stop` 或 `resume`。追加预算用 `resume --add-rounds N`，仅追加用户授权的正整数轮数。BLOCKED 补齐条件后显式 resume；COMPLETED 不重开，实质换题新建专题。
4. stop 返回确认后才修改目标、状态或待执行探针；未提交调用可能重跑，工程副作用不自动撤销。失败即停并提供日志入口，不自动无限重试。
5. 依据 JSON 状态汇报：COMPLETED 为研究目标达成；BLOCKED 给出待补条件；BUDGET_EXHAUSTED 给出剩余问题；IN_PROGRESS 给出下一动作。run/resume 退出码分别为 0、4、5、3，错误为 2。研究完成不意味着代码合并、独立审核或发布。

只在用户要求整理时生成报告，调用 archa-log。实时查看使用工作台，不把日志文本推测成未发生的模型活动。
