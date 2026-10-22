# OPC 运行底座复用核查

核查日期：2026-10-21。范围：控制流程、独立审核、恢复、预算与外部实验。本文是选型证据，不是集成验收报告。

## 1. 判断与减法

**先复用执行能力，再补 OPC 业务合同；不要让多个框架同时决定项目完成。** 交接文档推荐 Argus 有源码依据，但它的 `done` 不能直接映射成 OPC 的 `accepted`。本轮重新读取固定提交源码，确认 typed review action、仅重试 reviewer、成本准入等能力存在；未运行这些项目的 daemon、真实模型后端、Docker 隔离或长作业恢复。

用户倾向状态机是合理的。需要区分三件事：状态机决定下一步是否合法；模型决定本轮研究什么、怎么实现；evaluator 和 reviewer 判断实际产物。把所有推理写成状态转移会失去探索能力，把所有转移交给提示词又会丢失运行保证。这是设计推断。

首版删除公司组织层级、常驻“部门”、多 Master 竞争调度；推迟 harness 自修改发布和 SoL-Pi 效率优化。保留独立 reviewer、固定提交、预算与恢复，因为删除其中任何一项都会使“能持续自主迭代且结果可复核”这一结论失去依据。

## 2. 本轮证据等级

| 对象 | 固定版本 / 本轮来源 | 本轮实际做过 | 尚未做过 |
| --- | --- | --- | --- |
| ArgusAgent | `fdfeb715b0749db176c7d8b3212a717fb81087ba` | 读 review actions、bridge、运行配置、完成门、审核重试、成本代码 | 安装、真实后端、隔离、崩溃恢复集成测试 |
| LongHorizon-Harness | `d53df0aa11e8506dfc9518ef63620c62baee04d3` | 读 Manager→Auditor 调用及 resume service | 运行其完整服务；复现交接文档旧审核探针 |
| RD-Agent | `484776c211e4fbbeef03e0ec00d6bbee7362a4f4` | 读 research loop 与 dump/load/checkout | 运行科研任务、验证 provider 或评估器 |
| SoL-Pi | `219568034fa54ed121ede80961655e33dfb9d0e3` | 读扩展注册入口 | 安装 Pi、复现论文、度量效率 |
| LangGraph | 官方文档，访问 2026-10-21，未锁安装版本 | 读 checkpoint、interrupt 与恢复语义 | 本文未安装或运行 |
| Temporal | 官方文档，访问 2026-10-21，未锁安装版本 | 读 Workflow/Activity、重试、幂等和取消语义 | 本文未部署服务或 worker |

交接文档中已有的测试计数属于前次材料，本轮没有重新跑，不能算本轮实测。下文“没有证明”指所核路径未提供完整证据，不等于声称项目所有代码都没有该能力。

## 3. 复用矩阵

| 项目 | 可直接借用的部分 | OPC 仍须负责 | 定位 |
| --- | --- | --- | --- |
| ArgusAgent | Engineer↔Reviewer 调用、typed actions、reviewer 单独重试、成本准入；更完整 UI/daemon 可另做集成验证 | TaskSpec/Submission 绑定、接纳服务、累计任务预算、实验 job 对账、权限部署 | 最接近交接方案的执行基底候选 |
| LongHorizon | Manager/Executor/Auditor 调用、轮次 ledger、continue/retry 生命周期 | 提交内容绑定、审核失效、科研证据和完整费用合同 | 备选；本轮不与 Argus 同时接 |
| RD-Agent | hypothesis→experiment→coding→running→feedback→trace 的研究分层 | 独立签署接纳、冻结产物、外部作业账本 | 复用流程和领域组件，不替代接纳权威 |
| SoL-Pi | 工具输出与上下文效率扩展 | 所有 OPC 主循环与业务接纳 | 推迟；先量到 worker 成本瓶颈 |
| LangGraph | 显式图、checkpoint、条件分支、interrupt/resume | 身份权限、业务接纳、预算、外部副作用幂等 | 适合从状态机出发的小型控制层 |
| Temporal | durable Workflow、Activity 重试、事件历史、长作业等待与取消协议 | 领域合同、独立审核、费用、外部资源幂等 | 有跨机器长仿真/EDA 作业后优先评估 |

## 4. Argus：可以复用，但不能抹平两个完成状态

`ReviewActions.dispatch` 验证结构化工具参数，并把当前调用的决定保存在 `actions.decision`；普通文字或文件里的“通过”不会制造这一赋值。`CallBoundBridge` 生成随机 bearer token，绑定 loopback 服务并校验请求。因此，它比仅靠 reviewer 提示词多了一层实际调用边界。[审核工具源码](https://github.com/microsoft/ArgusAgent/blob/fdfeb715b0749db176c7d8b3212a717fb81087ba/argus/reviewer/tools.py#L125-L262)、[bridge 源码](https://github.com/microsoft/ArgusAgent/blob/fdfeb715b0749db176c7d8b3212a717fb81087ba/argus/core/role_tool_bridge.py#L35-L149)

这仍不等于已验证操作系统级独立性。共享用户、可写 workspace、可读凭证、可改验收器会破坏边界。OPC 部署需验证作者不能写接纳库、不能取得审核凭证；reviewer 只读固定快照，复算输出写独立 scratch。不同角色名字和同一进程内自行签署不能替代这些验证。

运行入口把显式参数、`ARGUS_SKILL_REQUIRE_INDEPENDENT_REVIEW` 与 vertical 规则合成有效策略；不存在更严规则时审核可以豁免。该固定版本还默认 `ARGUS_SKILL_SAFE_MODE=false`，并由此设置 `dangerous_yolo`。因此接入 OPC 必须显式设独立审核和安全执行配置，再验证所选后端是否兑现；不能直接继承默认值。[运行入口](https://github.com/microsoft/ArgusAgent/blob/fdfeb715b0749db176c7d8b3212a717fb81087ba/argus/apps/_runtime_execute.py#L659-L728)

审核基础设施失败的路径会只重试 reviewer，保存已有 Engineer 结果；缺失执行 host 会转 `infra_blocked`。这适合昂贵仿真已经完成、仅审核中断的情况。OPC 适配时应保持同一个 submission，而不是自动重新运行实验。[重试源码](https://github.com/microsoft/ArgusAgent/blob/fdfeb715b0749db176c7d8b3212a717fb81087ba/argus/engineer/round_reviewer.py#L508-L566)

成本模块用 settled ledger、在途观察和未知费用负债计算准入；`_unpriced_policy()` 的默认值是 `block`。可复用这套事实来源，但需要在 OPC 中映射 campaign/task/attempt，给审核预留额度，并接入 GPU、仿真器、EDA 费用；不能把每日模型限额当成全部任务预算。[成本模块](https://github.com/microsoft/ArgusAgent/blob/fdfeb715b0749db176c7d8b3212a717fb81087ba/argus/core/cost_control.py#L355-L449)、[未定价默认值](https://github.com/microsoft/ArgusAgent/blob/fdfeb715b0749db176c7d8b3212a717fb81087ba/argus/core/cost_control.py#L802-L807)

`ARGUS_SKILL_EXTERNAL_COMPLETION_GATE=acceptance/current.json:satisfied` 能提供项目完成门，但实现只解析路径并读取值是否严格为 `true`；未配置则关闭，没有在此校验 submission hash、签署者或文件 owner。它可以消费 OPC 的只读投影，不能自己成为 OPC 验收器。[完成门源码](https://github.com/microsoft/ArgusAgent/blob/fdfeb715b0749db176c7d8b3212a717fb81087ba/argus/core/external_completion_gate.py#L20-L58)

建议语义固定为：

```text
Argus mission done = 本次执行及原生审核循环收尾
OPC accepted = 指定 TaskSpec 修订下，指定 Submission 获得有效独立审核并通过接纳检查
```

Ge 下游依赖与用户交付只能消费后者。一次评审签署至少绑定 `task_id + task_spec_revision + submission_id + manifest_hash + evaluator_revision`，并由实际调用身份提供 signer，不能相信 payload 自报的角色名。

## 5. LongHorizon、RD-Agent、SoL-Pi 的边界

LongHorizon 的 Manager 真实调用单独 Auditor episode，保存原始轨迹和结果；不是只有文档描述。但所读主路径把自然语言审核报告传给后续轮次，并未在该处展示不可变提交的哈希接纳协议。[Manager 源码](https://github.com/AMAP-ML/LongHorizon-Harness/blob/d53df0aa11e8506dfc9518ef63620c62baee04d3/src/lh_harness/manager.py#L778-L822)

其 `continue` 复用 run ID、目录与历史 rounds，并递增 resume epoch；`retry` 新建 run，从保存的任务与配置重新开始。源码也存在生命周期幂等键。它解决的是 harness 进程与轮次恢复，不能据此推断外部 EDA/GPU 作业也实现 exactly-once。[resume service](https://github.com/AMAP-ML/LongHorizon-Harness/blob/d53df0aa11e8506dfc9518ef63620c62baee04d3/src/lh_harness/supervisor/service.py#L2234-L2505)

RD-Agent 的循环与用户“专家→设计→实验→反馈”的结构最接近：假设器基于 trace/plan 提案，转换实验，coder 实现，runner 运行，summarizer 反馈，再写 trace。它是值得复用的研究组织方式；summarizer 反馈不自动等于独立验收签署。[研究循环](https://github.com/microsoft/RD-Agent/blob/484776c211e4fbbeef03e0ec00d6bbee7362a4f4/rdagent/components/workflow/rd_loop.py#L184-L241)

其 checkpoint 使用 dump/load；`checkout=True` 会截断恢复点之后的 session 文件与日志，传入新目录则保留原件。OPC 的原始失败历史不能随回滚消失，因此适配应采用保留历史或新 lineage 的方式，不直接照搬截断模式。[恢复实现](https://github.com/microsoft/RD-Agent/blob/484776c211e4fbbeef03e0ec00d6bbee7362a4f4/rdagent/utils/workflow/loop.py#L427-L528)

SoL-Pi 注册 Action Fusion、ObservationPack、Evidence-Preserving Reducer、Online Context Compact 四种可配置扩展。该入口证明其定位是 Pi worker 能力扩展；不能由此声称它已经提供 Ge 的公司主循环、预算、独立接纳或外部作业管理。[注册源码](https://github.com/NVlabs/SoL-Pi/blob/219568034fa54ed121ede80961655e33dfb9d0e3/src/sol-pi/index.ts#L14-L50)

## 6. 状态机底座的竞争路线

| 路线 | 适用条件 | 收益 | 代价 / 失败点 |
| --- | --- | --- | --- |
| A：Argus + OPC 合同/接纳服务 | 先要 UI、后台运行、现有 agent 后端 | 最大化复用交接方案 | 原生 done 与 accepted 必须分开；需验证任务事件与审核映射 |
| B：LangGraph + OPC 服务 + worker adapters | 首要目标是简洁可测的状态图、Python 本地流程 | 节点与条件边显式，容易替换专家/设计/验证实现 | UI、作业、权限和预算仍需集成；不要再让 Argus 成第二个 Master |
| C：Temporal + OPC 服务 + Activities | 大量小时/天级外部仿真、远程资源、跨机器重启 | 运行持久性、重试、信号/等待更成熟 | 额外服务与运维；仍需下游幂等、资源取消和费用对账 |

LangGraph 的 checkpointer 保存图状态，支持本地 SQLite 与生产数据库实现；恢复同一 `thread_id`，失败并行步已完成的节点可通过 pending writes 避免重跑。`interrupt` 所在节点会从头恢复，前置副作用必须幂等。[Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)、[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

Temporal Workflow 用事件历史重放确定性控制流程；模型推理和外部 I/O 应放 Activity。Activity 可能执行多次，完成回执丢失时仍可能重试；下游 idempotency key 才能避免重复启动。取消需 Activity 心跳与配合，外部工具还要自己的 cancel/reconcile。[Workflow](https://docs.temporal.io/workflow-execution)、[Activity definition](https://docs.temporal.io/activity-definition)、[Activity lifecycle](https://docs.temporal.io/activity-execution)

**本轮建议：保留 A 为第一集成候选，同时把 OPC 合同定义为与 A/B/C 无关。** 若首个纵向验收显示 A 的事件、固定提交或权限需要大量侵入式改造，切换 B；进入跨机器昂贵作业后再用 C 替换运行层。路线选择不应改变 TaskSpec/Submission/ReviewDecision。

这不是同时引入三个调度器。每次部署只选一个执行调度权威，OPC 接纳服务只裁决业务事实。原型可以用小型本地状态机验证协议；这种验证不证明 Argus、LangGraph 或 Temporal 已完成集成，也不应演变为重新造通用 durable engine。

## 7. 最小集成验收，应先于大平台开发

1. 用冻结 TaskSpec 启动一个有有限预算、固定评估器的小任务，保存实际角色调用 ID。
2. 设计者提交不可变快照；reviewer 独立复算并给 Standards、Spec 两轴结论，再单列实验有效性/可比性/主张范围。
3. 注入错误候选，确认退回；修复生成新 submission；旧审核不能接纳新版本。
4. 审核进程失败，只恢复审核；已完成昂贵实验不得被重复启动。
5. 在外部作业提交后、收到 job ID 前制造中断：恢复必须通过同一幂等键查询，不能盲目重提。无法确认则 `RECONCILING`/阻塞。
6. 测试失败尝试、超时、取消与未定价调用都留下预算记录；审核预留不足时禁止开始新实验。
7. 暂停后不再派发新节点；运行中 job 的处理按 `drain`/`cancel` 区分，取消未确认不得声称已停。
8. 最后一次审核结论、代码 hash、输入、工具版本、raw logs、指标与交付声明逐项一致。

只有这些结果完成，才能说“所选底座上的 OPC 纵向闭环跑通”。仅有手工状态图、角色提示词、fixture 回包或数值评分改善，都不足以支持这个结论。
