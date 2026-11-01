# 06: 标准重验与 revision 历史汇总

**What to build:** 用户明确授权调整验收标准后，可用适用的已有成果按新 revision 判定；验收文档末尾展示各 revision 的已有情况，查看历史不会触发重复检验。依据 [S4 规格](../spec.md)。

**Blocked by:** 01 — 数值目标与完成判定贯通

**Status:** resolved

- [x] 修改标准需要用户授权及新 revision，已有明确授权不重复确认；不能从审核建议、停止理由或沉默推断降标授权。
- [x] 仅验收标准变化且证据仍适用时，沿已有旧成果重验入口判定，不创建执行 Run 或重新开发；继续执行则按新 revision 新建 Run，不清零累计用量。
- [x] 执行目标、输入或评价器变化不被当作仅标准重验；测量不再适用时说明原因并按实际影响补验，而非无条件沿用。
- [x] 原执行 revision、候选及失败报告保留；新报告标明实际验收 revision，不将历史未达标改写为通过。
- [x] 验收文档末尾从既有记录汇总每个标准 revision 最近一次验收的候选、结果及报告链接，无记录显示未验收；同 revision 多次验收的原记录按需可查。
- [x] 新标准尚未验收时不能换 revision 编号沿用旧通过；不同候选的结果不能因同一 Task 而混淆。
- [x] 生成和读取表格不调用 Worker、Reviewer 或测量，不重验旧 revision，不建立第二套历史状态账；相关观察入口保持只读。
- [x] 用 94 ms 在≤90 ms 标准下未通过、授权变为≤95 ms 后按适用证据通过的独立案例验证；检查调用次数、历史表、未验收版本和多次验收，不依赖自动修复票。
- [x] 完成相关标准确认、证据复用、计量与观察回归，复用已有报告结构和原件，清理本切片无用途产物，不新增通用版本管理服务。



## Comments

2026-11-01 — 实施与验收：

- `62b2f29`（同步02集成后的实现分支 `8a38a3d`）：沿现有 promote/用户 standards confirmation 做仅标准重验；已有测量有效时引用 evidence_source，不创建执行 Run、Designer 或新测量，原执行 revision 与所验收 revision 分别保留。
- 既有 PROMOTION.md 末尾生成每个 acceptance revision 的最近一次记录表（候选、结果、原报告链接）；未验收版本显示 not_evaluated。同 revision 的旧明细保留在原报告，多候选按实际 selected_version 区分。Observer 通过只读账本及报告，复用 results.py 的纯数据投影动态展示新 revision，不导入 Engine、不发起检验、不写平行历史账。
- 新报告保留 acceptance_source_digest 作为已验收契约的内容身份，和既有 acceptance_task_digest 区分源契约与已解析配置。仅标准重验的 revision 也由已注册报告冻结；save_revision 修改该标准会分配新 revision，直接原地覆盖则拒绝重验。只读历史发现当前源契约已不同，明确 not_evaluated 与原因，不沿用旧通过。
- 连续轻量验收：100→94、r1≤90 失败；用户明确授权 r2≤95 后复用同份评价通过，Calls/用量保持、执行 Run 数仍为1，旧 JSON/Markdown 字节不变；r3无记录显示未验收；重复r2验收只更新最新链接；改选100候选不继承94证据且新增恰好一次评价。另覆盖原地改标准、自动新revision及 goal/objective/input/evaluator 执行条件变化在派发前拒绝。
- 红→绿：首条案例先重现 history 字段缺失；冻结案例先重现无 Run 的 r2被save_revision原地覆盖。6项新验收全部通过。相关组合回归初次揭示01测试误插3行及新guard遮蔽真实执行变更错误，已分别删除误插、将guard放在既有执行/授权校验之后；8项针对性复验通过。最终同组回归：合入02前 **58 passed, 139 deselected**（64.05s），合入02后 **58 passed, 139 deselected**（67.08s）；`git diff --check` 通过，提交后未再添加未验证代码。
- 相关组合命令：`pytest opc/tests/test_delivery_history.py opc/tests/test_engine.py opc/tests/test_research_loop.py opc/tests/test_brief.py -k 'history or revision or target or optional_requirements or selected_delivery or selected_nonchampion or confirm or promotion or delivery or observer' -q`。完整框架回归由全部切片合入后统一执行；本票只读观察通过 ObserverAdapter 验证，HTTP TestClient 与 DSH实机未运行，不计入通过。未启动正式研究考试或真实模型能力评估。

2026-11-01 — 03/06交叉验收补充：history row直接携带原report.candidate，旧报告缺candidate时仅按selected_version保留代码引用；表格候选列展示代码、task/claim/vN及成果来源，Observer使用同一版本投影。新增高层案例在相同代码commit下分别交付copy/v2、copy/v3，核对最近记录精确版本、两份历史表、旧原件不变与观察无调用/写账。`test_delivery_history.py test_delivery_candidates.py` **14 passed**（7.56s），`git diff --check`通过；未新增候选ID、哈希或状态账。

2026-11-01 — 06/本地预算交叉修复：通过公开 Engine.run/promote 红灯确认，同一 r1 源契约字节不变时，local wall cap 从300改400的新 Run 合法，但原冻结 guard 将解析后 budget 引起的 task.digest 变化误认为标准被覆盖。修复前移复用已有 acceptance_source_digest / frozen source_contract_digest 的计算，冻结 guard 与报告使用同一源身份；历史无 source 字段保留原 effective digest 严格兼容，不增加哈希、扫描或状态账。新增案例证明首 Run loss1通过后，后 Run loss17独立验收失败，未继承旧 complete；原 JSON/Markdown 字节不变，真实源标准原地改动仍要求新 revision。`test_delivery_history.py` **8 passed**（4.72s），`git diff --check`通过。
