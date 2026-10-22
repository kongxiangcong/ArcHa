# 独立 Standards / 工程可靠性轴审核

日期：2026-10-21。审核者：独立子 agent `research_runtime`。审查集为本轮新增的 `examples/gemv_loop/*.py`、`examples/gemv_loop/tests/test_loop.py`、`contracts/models.py` 与 `contracts/validate_examples.py`；当前目录无 Git 基线，因此按完整新增文件审查，未调用依赖 Git 固定点的完整 code-review 流程。

本次审核与实现调用独立，但共享操作系统用户和目录权限，不构成安全隔离。未修改实现文件。只在 `examples/gemv_loop/.tmp/review-standards/` 写负例和证据。

## P2：资源门检查声明参数，未检查候选实际使用的 TILE

初审位置：[domain.py:113](../examples/gemv_loop/domain.py#L113) 至第 122 行；`execute()` 用调用参数 `tile` 计算预期访问次数并判断累加器上限，却没有把候选模块 `TILE` 与该参数绑定。

固定工作负载恰好不能通过访问计数区分 `TILE=12` 与 `TILE=13`：两者的 `ceil(M/TILE)` 在 M=1、5、17、32 时相同。于是计划 tile=12、候选实际 TILE=13 会通过 Standards 和 Spec，但候选在 17/32 行工作负载中分配 13 个累加器，违反合同上限 12。最终报告仍将该实现标记为 tile=12 并有效接纳，导致资源门和结果归属错误。

最小复现：生成 `design(13)`，调用 `execute(candidate, 12, review=True)`，得到 Standards pass、Spec pass、`scalar_transfers=2586`。完整复现：正常搜索到第六轮计划 tile=12，只在设计后把 candidate.py 换为 `design(13)`，再执行实验、冻结、审核、决定；结果 `acceptance_currently_valid=true`、`best.tile=12`、第六轮 accepted=true。

证据：

- `examples/gemv_loop/.tmp/review-standards/tile-mismatch-result.json`
- `examples/gemv_loop/.tmp/review-standards/feedback-loop-mismatch/report.json`
- `examples/gemv_loop/.tmp/review-standards/feedback-loop-mismatch/attempt-006/plan.json`
- `examples/gemv_loop/.tmp/review-standards/feedback-loop-mismatch/attempt-006/candidate.py`

修复建议：在此受限模板原型中，显式检查候选的唯一整数 `TILE` 与冻结计划相等，并对实际候选参数执行资源门；不匹配直接失败。增加上述完整反例测试。若未来允许任意 agent 代码，则这还不足以证明实际峰值资源占用，应改用受控 IR、插桩或真实综合报告；本建议不把 AST 检查提升成安全沙箱。

状态：**已关闭（2026-10-21 独立复验）**。修复增加 `validate_tile()`，在执行前要求唯一、未遮蔽的顶层正整数 `TILE` 声明，并与计划参数严格一致；重复赋值、参数遮蔽等直接失败。修复位置为 [domain.py:82](../examples/gemv_loop/domain.py#L82) 至第 110 行。

本审核者重新运行原始负例，现得到 Spec fail，原因 `candidate TILE does not match frozen plan tile`；同参 `TILE=12` 正例保持 Spec pass、2586 transfers。另独立检查参数遮蔽和重复赋值均拒绝。复验原件：`examples/gemv_loop/.tmp/review-standards/tile-binding-recheck.json`；所验 domain.py SHA-256 为 `67f8994fedb98d13d48a8c34eb46d36c124523bb51dad4c0594807d4c71b3283`。本次未重跑全套测试，完整套件由实现者另行执行。

关闭范围是受限模板候选的声明与计划绑定漏洞。该修复不证明任意程序的真实峰值资源占用，也不构成代码安全沙箱。初审反例和旧运行原件保留用于追溯，不作为修复后的有效接纳证据。

## 其他核查结论

未发现其他应阻断当前受限演示交付的 P1/P2 问题。状态与事件在同一 SQLite 事务提交；job intent 先于进程启动；完成回执落库而 phase 尚未推进时可复用回执；未知在途作业保守阻塞的边界与 README 一致。哈希复核覆盖审核前、接纳前和历史报告查询，失败候选消耗 attempt。审核失败只重试 reviewer 且有上限。

本次没有将已明确披露的限制当成缺陷：没有 OS 权限隔离、没有独立 LLM reviewer、没有后台实时暂停/远端取消、没有跨机器对账、没有美元/token/wall-time 预算、没有通用生产合同接入。上述能力仍须作为生产接入的验收项；本原型不能证明它们已经存在。

合同模型的严格字段、有限数值、双轴 accept 条件与草案不能直接下发的约定一致。身份真实性、引用存在性、跨对象摘要、资源授权和完整预算语义被明确留给服务层，不能仅凭 schema 校验通过宣称完成。
