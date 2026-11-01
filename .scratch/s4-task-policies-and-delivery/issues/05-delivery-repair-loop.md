# 05: 终验缺口回流与范围内修复

**What to build:** 用户授权的任务在终验未通过后，根据真实缺口进入修成果、补证或补验收，并按变更影响复验；最终只能以有效交付或有依据的未完成收尾结束。依据 [S4 规格](../spec.md)。

**Blocked by:** 01 — 数值目标与完成判定贯通；04 — 独立审核逐项覆盖必需需求

**Status:** resolved

- [x] 将数值未达、正确性失败、审核未满足、证据不足与评价/审核执行失败的具体事实反馈给 Expert 或对应恢复入口，不以同一个“失败”安排盲目重做。
- [x] 成果需修改时，关联失败报告从所选候选开修复 Run；已关闭 Run 和旧报告不改写，已授权范围内不每轮请求批准，累计用量保留。
- [x] 仅 Reviewer 调用失败则补审核，不启动 Designer 或创建开发 Run；评价工具启动失败保留候选并补评价，不强迫修订契约。真实标准、目标或评价器变化仍走契约修订。
- [x] 证据不足明确缺项，由 Expert 选择补测、补分析或修成果；无可行下一步可未完成收尾，不自动降低标准或无限重试。
- [x] 修复按影响复验，不能只重试原失败项；执行逻辑变化覆盖相关正确性及契约要求的性能，无法确定影响范围时运行相关既有验收集。
- [x] 仅论述修改且测量对象、输入与条件不变时可引用有效测量并重新审核新论述；报告区分新执行与引用证据，不把旧整体通过复制到新候选。
- [x] 暂停、停止、预算和执行未知阻止不允许的后续派发；在结果或回执落盘后恢复，不重复开发、测量、创建修复 Run 或记账。
- [x] 贯通开发 A→B→终验缺陷→C、优化冠军未达目标后未完成收尾、探索反例后补齐边界解释并交付三类轻量流程；无收益结果、有效反证和失败证据保留。
- [x] 复用现有报告和只读观察展示修复来源、候选、缺口与后续结果，交付成功不自动应用主分支；用实际调用次数核对不重复执行。
- [x] 完成本切片相关回归及前三类流程集成验证；标准修订/历史表由 06 独立覆盖，不新增依赖。复用 S1–S3 测试设施，明确 HTTP 排除与 DSH 未实测边界，不运行正式研究考试。



## Comments

2026-11-01 — 实施与验收：

- 实现 `6d72b75`；同步最新01–04/06集成后为 `17f54ba`。报告 next_step 按真实事实区分 repair_candidate、supplement_evidence、retry_evaluation、retry_review、revise_contract 与 complete；保留全部具体阻断事实。已确认 target/正确性缺陷不被 Reviewer 故障掩盖，真实 scope/evaluator 冲突优先走修订；INFRA造成的缺指标不反推代码坏。无可用审核 verdict 也属于补审核。
- 既有 promote 持久 promotion_started 的 pid/候选/验收参数，重入复用原 Call 路径；评价/审核回执后、尚未计账回执后、报告落盘未登记时中断，恢复不重复调用或记账。unknown 明确阻断重放；完成回执可在暂停/停止或预算到限后仅收尾，缺少的下一调用仍受控制边界约束。
- 评价 INFRA 不作为可复用测量；修复通道恢复后仅补评价。Reviewer 调用失败或无有效回复仅补审核，均沿原 Run/候选且不启动 Designer。复现阶段 INFRA 同样补评价：复用可靠主评价与已完成样本，只补缺样本，报告列 executed/referenced 及原件来源，逐原件 commit 核对比较范围。新的明确 confirm 请求仍执行新样本，另一 Run 的 baseline 不借用旧基线。
- 需要修成果/补证时，在既有 create_run 单事务中保存 delivery_repair 来源，避免 Run 已建但来源未登记的空隙；重复消费同失败报告复用已有修复 Run，原关闭 Run 不重开，累计用量沿用。已确认来源的修复不再重复准备评价；完整终验按新代码执行所有相关 gates。仅论述/主张改版、代码及测量条件不变时，从已注册报告跨 Run 引用有效测量，重新审核新版本，不复制旧整体通过。
- Engine summary、opc report/status、Expert repair context 与 Observer 读取已注册报告，展示准确候选、验收 revision、complete、原报告链接及逐项缺口；Expert 可只读打开具名失败报告原件。历史仅计量 marker 保留来源且 failure=null，不虚构缺失细节。CLI --repair-promotion/--deliver 可直接消费补验收结果，预算拒绝以真实错误退出。archa-loop 消费 next_step 及完整候选（含主张版本），保持有限、依依据继续；通过不自动 apply。
- 三例贯通：开发 A 已保存但失败→从 A 修成 B→B终验边界失败→关联原报告创建 C 修复并全量验收，包含创建后中断恢复及幂等重复消费；优化100→94、≤90未达，终验失败后 Expert 有缺口地未完成收尾，无额外审核；探索反例 v1 缺边界解释→补分析为 v2，同代码交付，计入 preflight 仍零次新增测量、仅新独立审核。失败、无收益、反证与旧原件保留。
- 红→绿记录：先复现3类 promotion 重复执行、永久复用 INFRA、缺失失败分类、修复 Run 创建中断后重复/身份歧义、预算/控制抢在可靠回执前阻断，以及混合 target/审核故障误分流；逐切片修正。19项新高层验收通过。切片组合49 passed；同步集成与 source guard/binary 原件修复后的最终受影响组合 **76 passed**（63.40s），覆盖所有S4验收、tool boundary、prompt<2600、旧计量marker及03旧身份错误匹配。提交后无新增未验证代码，工作树干净，git diff --check通过。
- 中途较广针对回归为125 passed/4 failed；4项分别是 prompt 长度、旧 marker 来源缺字段、03两项旧错误措辞，均已在最终组合覆盖修正。完整框架回归由根流程统一执行；本票未把未重跑的其余广回归记为最终通过。
- 最终命令：`pytest opc/tests/test_delivery_repair.py opc/tests/test_requirement_review.py opc/tests/test_delivery_candidates.py opc/tests/test_delivery_history.py opc/tests/test_task_delivery_intent.py opc/tests/test_tool_boundary.py opc/tests/test_research_loop.py::test_context_bounds_machine_data_and_history opc/tests/test_research_loop.py::test_delivery_accounting_survives_engine_recreation opc/tests/test_research_loop.py::test_invalid_work_adoption_rejects_whole_decision -q`。受控 Worker/Reviewer 回执及轻量本地工具验证真实账本/成果/调用数；HTTP TestClient、真实 DSH 与正式研究考试未运行，不计入通过，不证明真实模型科研判断能力。

2026-11-01 — 审查修复开始：Spec发现有objective的仅论述修复仍初始化实测基线，以及修复入口预算检查未使用已授权的effective_budget。暂回claimed，在统一review-fixes分支修复并验收；其他五票状态保持。

2026-11-01 — 双轴审查修复验收：两项Spec P2均先以受控高层用例复现后修复。带objective的同代码论述修复，复用具名source report已可靠完成的选定测量初始化比较基线；沿原evidence_key核对commit/任务输入/评价器/toolchain/environment并沿用原报告的gates/metrics判断，记录baseline_source与referenced，不新建缓存或快照。用原baseline=17、selected=10的案例核对新比较基线为10，Engine.evaluate_commit和真实Evaluator Calls均零新增；无objective分支标not_applicable，不虚构实测。环境漂移时真实重测为19，评价器INFRA如实抛错，不回退旧17。修复预算检查使用effective_budget：原10、已用10、授权20可继续且累计10保持；实际有效额度10耗尽或hardlimit10仍阻止新Run。该授权案例沿既有具名准备回执保持ready，不重新询问授权。

最终针对验证：`pytest opc/tests/test_delivery_repair.py opc/tests/test_delivery_history.py opc/tests/test_resource_limits.py -q` **69 passed**（24.44s）；git diff --check通过。其余切片状态未改，完整框架回归及审查复核由根流程接续；本次仍未运行HTTP TestClient、真实DSH或正式研究考试。

2026-11-01 — 完整框架回归发现10项回归：3项旧提示/身份错误措辞断言，7项S3依据修订后的未完成收尾被交付basis复核误阻断。暂回claimed，在原review-fixes集中修复并保护真实验收的basis约束。

2026-11-01 — 全框架回归修复：实证复现根流程同10项失败；3项是等义prompt/身份错误旧字串，按含义更新断言，保留失败可见、adoption未登记与调用行为断言。7项S3场景的真实原因是终止分支不区分意图，对legacy exhausted/close_incomplete也要求delivery_basis_review；生产逻辑仅将该复核限定request_acceptance。新增高层对照：工作采用copy/v1后出现v2，明确未完成收尾可关闭并保留旧basis、真实gap和变化，申请验收仍阻断；对已收尾候选直接promote也仍因未处理变化阻断，不继承完成。

针对10项及02/03/S3依据与adoption相关复验：`pytest opc/tests/test_engine.py::test_next_expert_receives_original_plan_and_measured_evidence opc/tests/test_delivery_candidates.py opc/tests/test_task_delivery_intent.py opc/tests/test_research_loop.py -k 'next_expert or basis or adopt or delivery_candidates or task_delivery_intent' -q` **38 passed, 90 deselected**（23.26s）；git diff --check通过。生产修复为一个意图条件，未抬prompt长度上限、未放松实际request/promote审核。完整框架再次验证由根流程接续，尚不将其计为通过。
