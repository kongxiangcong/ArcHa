# 02: 请求验收与未完成收尾分流

**What to build:** Expert 能继续选择工作、提出明确候选申请验收，或说明未完成但停止投入；用户从运行入口到报告都能看到真实意图，只有允许的交付请求进入终验。依据 [S4 规格](../spec.md)。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 复用已有决策与持久记录明确区分请求验收和未完成收尾，贯通 Worker 交接、Engine 与 CLI/Loop；不单凭 Run 关闭启动终验。
- [x] 开发允许选择已保存的未完成版本继续修复，并保留已知失败；并行分支最后返回不自动决定下一轮起点，不隐式合并成果。
- [x] Expert 按尚缺要求、证据和下一步预期作用判断继续价值，不按固定无收益次数停止，也不因预算有余而强迫继续。
- [x] 未完成收尾保存成果、缺口、停止理由及有依据的重开条件；不新增逐轮策略报告，不把停止表示为完成。
- [x] 已获交付授权的验收请求复用既有终验入口；最后一轮反馈仍须处理，不能因不再创建 Attempt 而遗漏。
- [x] 暂停、用户停止、预算退出、真实阻塞和执行未知遵守既有控制规则，不借收尾派发新的终验或审核。
- [x] 决策或候选可靠保存后中断，恢复不重复选择、派发、终验调用或记账；已关闭 Run 不原地重开，读取状态无执行副作用。
- [x] 用脚本化 Expert 分别验证有理由继续、申请验收和未完成停止，检查实际调用次数及 CLI/报告结果；完成相关恢复/控制回归并清理被替代收尾逻辑，不增加管理 Agent。


## Comments

2026-10-31 实施完成：复用 Expert 决策新增 `finish=request_acceptance|close_incomplete`，未完成收尾保留 gaps、停止依据、reopen_conditions；旧 exhausted 只表示未完成停止。选版与终结意图由账本同一事务保存，CLI 仅消费明确验收请求，关闭 Run 的可靠请求可继续验收且已有报告只读复用。报告、status 和 observer 显示同一 closure。批量分支保存候选但不按完成顺序替换默认工作版本，已有 base_attempt 续作保留失败事实。

最后反馈：Attempt 数额度用尽时仍可在其余预算和控制允许下分析最后结果，不创建新工作，也不借预算退出派发终验；真实 token/wall/accounting/control 退出沿既有边界保留 pending 事实。更新 archa-loop 的终验触发措辞。

验证（受控 Worker/本地工具，不启动正式研究考试）：`/tmp/archa-results-venv/bin/python -m pytest -q opc/tests/test_task_delivery_intent.py` 6 passed，覆盖未完成收尾、显式验收及只执行一次、legacy stop、终结交接恢复、并行选版、最后 Attempt 反馈。预算/暂停专项 `test_attempt_dag.py test_resource_limits.py test_engine.py -k 'attempts or budget or pause_during_evaluation'` 14 passed。六文件相关回归初次 226 passed/3 failed；三个开发中失败（prompt 长度、旧 CLI 测试的隐式终验、双 worker 提示）修复后针对性复跑通过：完整 context 历史/原件用例等 8 passed，原计划证据/CLI/双 worker 提示 3 passed；prompt 保持小于 2600 字符。已有未完成候选续作、分支依赖、可靠回执/计量/控制回归包含在该回归中。HTTP fixture 不在本票执行范围；真实 DSH 未实测。
