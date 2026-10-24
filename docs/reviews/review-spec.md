# 独立审核：Spec 与结论边界轴

日期：2026-10-21。审查主体：独立研究/审查子 agent；本次审查不参与原型代码编写。没有 Git 历史可作为 diff 基线，审查集合明确为本轮新增的实现方案、`contracts/`、`examples/gemv_loop/` 及其正式运行原件。借鉴双轴方法，本文件只报告需求与结论边界轴；不是原型自动派发的 LLM reviewer 回执。

## 发现

### P2：容量校验信任声明 tile，没有验证候选实际 TILE（已关闭）

- 位置：`examples/gemv_loop/domain.py:113-122`。
- 依据：方案要求“只有正确性与资源门通过才能讨论改善”，用户要求验证 agent 独立审核实验结果；交接要求候选不能靠放宽验收获得进步。
- 可复现：把 `design(13)` 的源码交给 `execute(candidate, 12, review=True)`，结果是 `standards=pass`、`spec=pass`、`scalar_transfers=2586`。这次使用内存对象提供源码，没有修改候选文件或生产代码。真实模板需要 13 个累加器，超过合同 12；但校验只查看外部参数 12。四个工作负载对 tile 12/13 的输入读取数恰好相同，因此公式核验没有揭穿错误声明。
- 影响：当前自动模板生成路径恰好保持两者一致，所以正式八轮原件未受影响；但“资源门能够阻挡不合法候选”的实现边界比文档表述窄，候选或未来设计 adapter 错报参数就可能错误通过。
- 建议：至少要求源码 `TILE` 是正整数并与冻结计划一致；在当前受限模板范围内明确候选形状约束或测量实际峰值累加器。加入“实际 TILE=13、声明 tile=12”的拒绝测试。修改 evaluator 后重新运行，不能沿用旧 domain hash 的接纳。
- 复核：当前 `domain.py:82-110` 在执行前要求唯一、不被遮蔽的顶层正整数字面量 `TILE`，并与冻结计划匹配。独立重跑同一 `actual TILE=13 / planned tile=12` 反例，当前返回 `Spec=fail`，原因为 `candidate TILE does not match frozen plan tile`，未产生指标。新增四个实例覆盖该错报、bool、表达式和重复声明；在本轮受限模板范围内关闭此问题，不外推为任意程序资源占用分析。

### P2：复用表列出的 AAT 快照与本轮源码证据不同（已关闭）

- 位置：`OPC 框架实现方案.md:46`。
- 现状：主表列 `4a137bb1…`；本轮 `docs/research/optimization-reuse.md` 实际检查的是 v2 `4c7d42537ae3c8f4f8da778f2c7794a94af73287`，尤其 Gowin 评测与旧时序模型限制依赖该版本。
- 影响：实施者按主表复用可能拿错版本，不能按一个 SHA 复核引用链。
- 建议：改为已核查 v2 SHA，或分列 main/v2 并各自说明证据。不要把交接文档的旧快照当成本轮已读取代码。
- 复核：主方案第 46 行已改为 `AAT v2 4c7d4253…`，与本轮研究文件的固定 SHA 一致。

## 已确认的范围

- 用户的三部分结构、Ge 唯一运行入口、专家—设计—验证反馈循环均在设计中覆盖；控制逻辑与 skills 分离。
- 生产协议包含版本/manifest 绑定、身份由服务登记、预算、外部作业对账、暂停与取消语义。Pydantic/schema 只负责结构，鉴权和跨对象业务检查仍由待实现服务执行；文件已明确这个边界。
- 原型明确为确定性专家、模板设计器和独立 Python 子进程验证；没有宣称已经实现真实 LLM 自主闭环。AST Standards 检查也明确不等于完整可维护性审查。
- 正式报告有 8 次尝试、5 个有效候选、3 次容量拒绝、16 个实验/复核作业，停止原因为预算耗尽。读取的报告 domain hash 与审核时源码一致。
- `(4665-2586)/4665 = 44.565916…%` 与结果报告一致；文档限定为四个固定形状、精确整数和解析流量模型，没有转写成实际硬件速度、能量或最优架构。
- 暂停/恢复、旧审核失效、未知作业不盲发、审核单独重试有针对性测试；不等于已经验证活跃远端 job 认领或生产多机持久运行。

## 未实现而非本轮缺陷

Ge 实际对话/API 服务、通用合同到 demo 的映射、真实模型 adapter、只读/隔离权限、外部作业对账服务、token/美元硬预算、真正独立模型 reviewer、完整 DAG 与真实硬件评测均在后续阶段。当前可以交付的是“实现设计 + 受限工程闭环可行性证据”，不能把它标为“OPC 真实 agent 平台已验收”。

## 修复后的证据复核

- 已补读 [validation.md](../validation.md) 与 [RESULTS.md](../../examples/gemv_loop/RESULTS.md)。正式证据为 `examples/gemv_loop/runs/final-reviewed-20261021/`；旧 `final-20261021/` 不能代表修复后的 evaluator。
- 独立读取新 `report.json` 和 `paused-report.json`：暂停时 phase=paused、2 轮、4 个作业；最终 phase=complete、reason=budget_exhausted、8 轮、16 个作业；暂停时全部 invocation 保留。最终 best tile=12、scalar_transfers=2586，5 个有效候选、3 次拒绝，`acceptance_currently_valid=true`、`invalid_submissions=[]`。报告 domain hash 与当前 evaluator 原始 bytes 一致。
- 已读取 `runs/tests-reviewed.xml`：12 个测试、0 failures、0 errors；包含新增四个拒绝实例。复核只重跑了上述最小错报反例，没有重复整个测试套件。Ruff/Mypy 通过依据主实施者验证记录，本审核未另行重跑静态检查。
- 验证报告把模型流量、固定形状、独立子进程、真实模型尚未接入、生产权限/预算/恢复未实现分别说明，未发现需要纠正的结论越界。

结论：原 2 项 P2 已复核关闭，无未关闭 P1/P2。可接受本轮 P0 的设计与离线可行性范围；P1 真实 agent 闭环仍待实施和验收。
