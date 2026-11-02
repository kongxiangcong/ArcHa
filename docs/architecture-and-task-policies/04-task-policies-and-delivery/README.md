# S4 任务策略、成果接纳与交付闭环

状态：需求及轻量测试范围已确认（2026-10-31），[实现规格](../../../.scratch/s4-task-policies-and-delivery/spec.md)已发布为 `ready-for-agent`。[六个实现事项](../../../.scratch/s4-task-policies-and-delivery/issues/)已按用户确认的拆分发布，均为 `ready-for-agent`；尚未实施或执行 S4 验收，未启动正式研究考试。

本页兼作“整体架构与任务策略 / S4”专题白板，保留导航、设计依据及事项入口。行为与验收要求以实现规格为唯一权威来源，不维护两份实施要求。

## 阅读入口

- [Implementation Decisions](../../../.scratch/s4-task-policies-and-delivery/spec.md#implementation-decisions)：任务策略、字段职责、候选、审核、修复及历史汇总。
- [Testing Decisions](../../../.scratch/s4-task-policies-and-delivery/spec.md#testing-decisions)：已确认三类轻量案例、既有测试入口和必要故障分支。
- [Out of Scope](../../../.scratch/s4-task-policies-and-delivery/spec.md#out-of-scope)：减法及正式考试边界。
- 接续依据：[S1 交付记录](../../../.scratch/s1-task-contracts-and-onboarding/spec.md#交付验证)、[S2 交付记录](../../../.scratch/s2-attempts-and-worker-handoffs/spec.md#交付验证)、[S3 交付记录](../../../.scratch/s3-evidence-and-shared-knowledge/spec.md#交付验证)。部分历史入口保留实施前状态，以实际交付记录为准；本轮未重跑这些验证。
- 阶段导航：[总规划](../ArcHa_Phased_Development_Plan.md)、[S0 共同边界](../00-foundations-and-test-methods/README.md)、[后续 S5](../05-debugging-workbench/README.md)。

## 讨论依据与取舍

**进展、继续工作与交付是不同判断。** 正常 CSV 输入可读但错误处理仍失败的版本，可以继续修复；100 ms 改到 94 ms 可以成为冠军，但未达到 90 ms 交付门槛；有效反证能够回答真假问题，却未必补齐契约要求的机制解释。三例用于澄清行为，不是实际研究证据。

**复用 target，避免两份阈值。** 源码 `accept.judge` 已区分收益与目标，`promote` 却仅对 target 未达标记警告。讨论选择明确 target 的硬门槛含义，保留 objective 的比较职责；另一条路线是将全部门槛迁入 requirements，但会牵动目标展示等路径，当前没有必要。历史契约不静默改义，具体约定见规格。

**候选与审核还需贯通。** `Engine.choose_work` 的 selected_version 当前只保存代码 commit；`promote` 经 results_context/claims() 读取当前主张，不能保证就是选定交付版本。已有 adopted_claims 是工作依据，不等同于交付清单。Reviewer 的 requirement_findings 当前是字符串列表，整体 accept 会将全部 needs_review 项标为通过；需沿已有接口补齐准确对象与按需求覆盖，无须新审核服务。

**闭环已有入口，缺少清晰意图。** 已读 Engine.run、CLI cmd_run 和 archa-loop 交付指引：run --deliver 已串联终验，--repair-promotion 已承接修复；不能据 Engine 内没有直接调用 promote 就认为闭环完全缺失。真正需要补齐的是请求验收与未完成收尾的区别，以及失败分类和后续行动的一致性。

**避免重复检验，不排斥历史展示。** 用户最终确认验收文档末尾保留各 revision 已有结果表；此前“不并列展示新旧结果”的提议已被替代。表格是已有记录的只读汇总，不另建状态账或重新检验旧 revision。

## 实现事项（已确认并发布）

每票包含自身的持久事实、CLI/观察输出、必要测试及旧路径清理；不按技术层分票。当前没有必须先做的独立预重构。

| 编号 | 标题 | Blocked by | 可独立验证的交付 |
| --- | --- | --- | --- |
| 01 | [数值目标与完成判定贯通](../../../.scratch/s4-task-policies-and-delivery/issues/01-target-completion.md) | 无 | target 未达阻止完成，中间冠军仍可更新；字段职责、准备与结果展示一致，覆盖历史语义边界 |
| 02 | [请求验收与未完成收尾分流](../../../.scratch/s4-task-policies-and-delivery/issues/02-delivery-intent.md) | 无 | Expert 明确选工作、请求验收或未完成收尾，CLI/Loop 只在允许时进入终验，控制与恢复不重复派发 |
| 03 | [固定探索交付对象与版本](../../../.scratch/s4-task-policies-and-delivery/issues/03-delivery-candidate-versions.md) | 02 | 从交付决策保存成果/主张版本，审核与报告使用同一候选；相关修订先处理，反证和缺口保留 |
| 04 | [独立审核逐项覆盖必需需求](../../../.scratch/s4-task-policies-and-delivery/issues/04-requirement-review-coverage.md) | 03 | 同次审核按需求给出判断和依据，遗漏或证据不足不随整体 accept 放行；覆盖明确主张版本的探索验收 |
| 05 | [终验缺口回流与范围内修复](../../../.scratch/s4-task-policies-and-delivery/issues/05-delivery-repair-loop.md) | 01、04 | 数值未达、审核缺口和执行故障进入正确后续路径；修成果、补证与补验收按影响复验，覆盖三类连续案例 |
| 06 | [标准重验与 revision 历史汇总](../../../.scratch/s4-task-policies-and-delivery/issues/06-standards-history.md) | 01 | 明确授权的新标准重验适用成果，报告末尾汇总各 revision 最近结果；不为历史展示重复检验 |

03 依赖 02 的交付决策入口；04 依赖 03 的准确审核对象；05 依赖 01 的完成判定与 04 的逐项缺口（间接包含 02/03），不依赖历史表；06 依赖 01 的新门槛语义，不依赖自动修复。01/02 可先推进，06 与后续交付候选链可并行；共享文件不是新增依赖边的理由。

六票粒度与阻塞关系已获用户确认。后续实施从无阻塞的 01、02 开始，按各票依赖推进；实际验证记录留在对应事项，不另建报告副本。本轮仅发布规格和事项，不启动编码或正式考试。
