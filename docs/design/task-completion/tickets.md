# 任务完成主线：实施 tickets

日期：2026-10-27。依据：[spec.md](spec.md)，基线 `c111a72`。

**2026-10-27：用户已确认 spec、tickets、validation，授权顺序实施 T1–T6 及一组预算内真实 pilot。**
本清单是本次改造唯一的 ticket 状态入口，不另建工单系统或逐票计划/总结文件。

补充：用户已确认单任务工程验证方向并授权构建素材。[validation.md](validation.md) 和任务 fixture 已准备，素材自检通过；这不是 T1–T6 实施。后续发送 [开发提示词](development-prompt.md) 即明确授权执行这些 tickets 和有预算的 paired pilot。

## 执行约定

- 用户确认 spec 与清单后，严格按 T1 → T2 → T3 → T4 → T5 → T6 实施，不并行开展多个 ticket。
- 单票开工改为 `in_progress`；实现及针对性验证通过后改为 `resolved`，在该票末尾记录提交、验证与实际限制。先完成当前票再开始下一票。
- 每票至少一个独立提交，代码、相关测试与必要说明一起提交；最终继续更新本 PR。`resolved` 表示满足该票验收，不等于整个改造已交付。
- 验证失败在当前票内修复；真实外部阻塞记为 `blocked` 并说明，不改成新流程层解决。
- 不为每票复制 spec、完整运行日志或生成新报告；结果写在本清单，原始测试产物保持临时。
- 本轮规划与素材 PR 不运行真实模型或 onboard；素材自检不需要模型服务。T6 的真实成本对照使用 validation 中已给定的配置与预算，不要求用户提供素材。

## 总表

| Ticket | 交付行为 | 前置 | Spec | 验收 | 状态 |
| --- | --- | --- | --- | --- | --- |
| T1 | 无数值目标也能积累、恢复和选择成果 | 用户确认 | R1–R3 | A1–A4、A11 | resolved |
| T2 | 选定成果终验，证据补齐直接收尾 | T1 | R5 | A3、A5–A7 | resolved |
| T3 | 精简模型输入，保留按需证据 | T2 | R6、R4.6 | A8–A9 | resolved |
| T4 | 放宽工作表达、验证按需、直接任务接入 | T3 | R4、R8 | A4、A7、A12 | resolved |
| T5 | 确定性请求拒绝停止调用 | T4 | R7 | A10 | resolved |
| T6 | 全链路回归、工程任务对照与旧 benchmark 退役 | T5 | §5–§6、R8、validation | A1–A12 + paired pilot | blocked |

## T1：完成条件合同与连续工作版本

**目标**：无 objective 的任务从功能未完成基线进入同一引擎循环，连续保存成果并可恢复；研究停止时能选择需要交付的版本。

主要位置：`opc/core/config.py`、`accept.py`、`engine.py`、`model.py`、必要的 `ledger.py` 事件读写，以及 `opc/adapters/prompts.py` 中依赖冠军必然存在的呈现。

实施内容：

1. 允许 objective 缺省/null，移除 required metrics、gain、target 展示与初始化中对 objective 必然存在的假设；保留绝对验收约束，明确拒绝无基准的相对排名配置。
2. 贯通 `check → preflight → open_run/reconcile → attempt → summary`。功能失败基线与执行通道失败分开；无 objective 不创建伪冠军。
3. 复用 `base_attempt` 和已有候选事件维护工作起点及停止时的交付选择。默认、显式旧候选、基线选择按 R3 处理；只推进已完成授权保存的修改。
4. 同步暂停/恢复、旧优化 run 读取、费用和报告，使“不排名/未测量/尚未完成”有真实表达；不另建状态文件。
5. 此票不完成终验改造；在 T2 完成前，无 objective 的交付不能沿旧 champion 路径误报成功，应明确尚不支持。不能为了让旧 promote 工作伪造冠军记录。

删除/替代：无 objective 的强制评分与冠军初始化；将所有非涨分工作解释为失败推进的语义。

验收：

- A1–A4：至少一个两步开发夹具覆盖未完成基线、未完成中间成果、恢复和 stop 选旧候选；核查最终 commit 的实际内容。
- 同一夹具含 worker 失败/越界对照，确认默认起点不被污染。
- A11：原数值优化的基线、候选续用、champion 比较及旧 run 恢复用例继续通过。
- 针对性测试放入 `opc/tests/test_codex_and_config.py`、`test_engine.py`、`test_research_loop.py`，并运行受影响套件。

完成记录：2026-10-27，T1 独立提交（本提交）。无 objective 合同、失败基线、连续工作版本与 stop 选版；新增恢复/选版/失败 worker/越界测试。受影响 engine、research_loop、codex/config 套件通过（见提交验证）。终验留到 T2；未创建伪冠军。

## T2：选定版本交付与证据收尾

**目标**：没有涨分历史的完整成果也能接受终验；补审阅证据直接附到被审版本，避免再次进入搜索。

主要位置：`opc/core/promote.py`、`engine.py` 的报告/版本选择读取、`opc/cli.py` 中对应参数与输出，以及既有 promote 测试。

实施内容：

1. 移除“两条冠军记录才可 promote”的门槛，累计 diff、范围与 evaluator 检查改为初始基线到选定版本；gain/重复性能确认仅在适用时执行。
2. 终验取得该版本的完整验证证据，检查必需 gates/constraints/requirements 与必要 review。修正 unmet 只作 warning、无 check 自动记为已覆盖等完成判断；不把探索停止转换为完成。
3. 复用 promotion 报告保存 reviewer 回执与被审 commit 的关系；同一版本已有适用的完整评价时，补 review 不创建候选、不重复测量。明确缓存来源及有效性边界。
4. 产品文档与外置审阅回执分开处理：前者可随同分候选交付，后者不用提交为代码；不按扩展名豁免评价。
5. 保留显式 apply、已有用户分支保护与 reviewer 隔离方式；报告具体缺口供后续专家修复，不新增自动修复/审批层。

删除/替代：冠军身份作为交付资格；补证据重新评分；把必要未满足条件只显示为警告却仍允许完整交付的路径。

验收：

- A3/A5：同分候选被选择后，交付实际包含其文档/能力；无涨分任务也可通过完整终验。
- 必需 gate 失败、指标缺失、requirements 不满足、必需 reviewer 缺失或拒绝，均不能完整应用；没有 review 需求时不额外强制 reviewer。
- A6：用评价器调用计数验证同 commit 补 review 不重跑产品；回执不得绑定其他候选。
- A7：产品、安装材料、工具环境变化时不借用旧证据；数值主张属于实际交付版本。
- 运行 `test_engine.py`、`test_research_loop.py` 及受影响 Codex/DSH reviewer 用例。

完成记录：2026-10-27，T2 独立提交（本提交）。选定版本完整 fresh 终验；未满足需求/约束/必需审阅均阻止交付。复用同 commit、冻结合同/评价器、工具及环境摘要的 promotion 评价，只补 review 不创建候选。84 项受影响测试通过，新增 selected/review/evidence 测试所在套件 17 项通过；真实 review 待 T6。

## T3：模型上下文去重与按需材料

**目标**：默认输入保留决策必要事实，同时停止把机器指标、历史和背景反复塞给模型。

主要位置：`opc/core/engine.py::context/attempt/save_conclusions`、`opc/adapters/prompts.py`、`opc/domain.py::experimental_data`、必要的 command domain 数据呈现。

实施内容：

1. 梳理最终 prompt、`context.json`、`research.json` 的重复关系，在现有材料上收敛默认输入；不新建材料索引服务或摘要文件链。
2. 分开机器判定指标与模型决策材料。按 R6 精简 baseline/champion/history/experiment/candidates；既处理很多标量，也处理大数组，不用 R03 名称白名单。
3. 保留关键实验条件、对照、分项结果、来源与真实不确定性；完整数据留原位置，专家可按需读取相关结构化材料，designer 继续读代码。
4. 默认历史不再因 improvement/pending 全量扩张；候选只给必要短信息，旧 ID 仍可续用；不删除历史事实。
5. conclusion 仅校验返回项的关联，不再要求完整清空 pending。原始缺失仍显示，框架不补造研究解释。

删除/替代：全量 metrics 多重序列化、prompt/材料双份注入、全改善历史保留例外、全 pending 强制结论。

验收：

- A8：在相同研究数据上分别使用小指标集、2,156 个机器字段和大数组，直接检查最终 prompt 与可见默认材料，原机器字段不得逐项进入；完整证据可找回。
- 用可解释实验对照证明关键数值、条件、异常代表项没有被简单删成一句主观结论。
- A9：超过现有窗口的改善/pending 历史不会全量注入；未展示旧候选可选择，省略旧结论仍能执行有效计划。
- 运行 `test_research_loop.py`、`test_codex_and_config.py`、`test_dsh_worker.py`；同步 scripted 策略真实依赖，不为兼容而回填全量上下文。

完成记录：2026-10-27，T3 独立提交（本提交）。必要指标投影、实验结构有界呈现、完整 evidence 引用、12 轮窗口与短候选目录；prompt 改为读取 research.json，结论允许按需返回。66 项受影响测试通过；新增 2,156 机器字段、1,000 cases、15 轮历史验证，research_loop 18 项通过。原始数据保留，未新增产物类型。

## T4：工作粒度、按需验证与直接接入

**目标**：明确开发任务能直接进入框架，designer 可完成一整步开发与调试，不再被强制实验格式或逐轮全量评价限制。

主要位置：`opc/adapters/worker.py`、`prompts.py`、`engine.py::attempt`、`opc/scaffold/brief.py`、`onboard.py`、`ONBOARDING.md`、`skills/archa-task/`、`skills/archa-loop/`，必要的既有初始化调用。

实施内容：

1. 放宽普通工作的 hypothesis/expected/falsifier 必填限制，保留可执行 changes 和必要身份/版本校验；Codex schema、DSH 解析、scripted worker 一致，不强迫模型虚构实验。移除仅按计划文字相同拒绝工作的规则，允许专家明确复测或从新状态重试。
2. 在现有 plan 中用最少意图表达是否正式评价，默认行为按 R4.4。未测量结果不得送去晋升冠军；显式无补丁新测量不被缓存短路。
3. 让 designer 在授权路径内修改开发测试并连续局部调试；冻结资产仍受原范围检查保护。清理笼统的“禁止修改 tests”提示。
4. 支持明确直接任务和无地图简报，复用现有初始化/onboard，不生成空地图或额外交接层；有地图时保留真实来源校验。
5. 将 `Objective: none`、Done when/requirements 映射、就绪与完成差异同步到实际接入说明；已确认交接复用，无需反复调查内部 runtime。

删除/替代：所有任务强制地图、无 objective 阻塞、普通开发强制实验五字段、每轮强制全量评价、全面禁止开发测试。

验收：

- A12：直接任务和地图任务都通过真实 brief 校验路径，缺少必要来源/验收依据仍清楚报错；onboard 无需真实模型的测试覆盖 prompt/映射约定。
- A4/A7：普通开发两步之间不自动全量评价；专家请求评价时执行，终验仍不可绕过；同文字的明确复测可执行，显式 fresh 测量保留。
- 允许路径中的开发测试可修改，冻结测试修改被拒绝；普通计划无需假设等字段，旧研究计划仍可执行。
- 运行 `opc/tests/test_brief.py`、`test_codex_and_config.py`、`test_dsh_worker.py`、`test_research_loop.py` 以及 `tools/tests/test_brief.py`、`test_research_skills.py`、`test_skill_installer.py`。
- 此票修改仓库内技能文件并随本分支提交，不触碰全局技能安装或用户项目 runtime。

完成记录：2026-10-27，T4 独立提交（本提交）。放宽为 title/changes，删除文字去重，evaluate 意图控制正式测量；开发测试遵从 editable/frozen。直接 Task 来源可省略地图，none objective 接入和技能同步。指定套件 104 passed/2 skipped；新增直接来源与默认局部/显式正式评价测试。全量 prompt 注入旧断言同步为单份材料读取。

## T5：无有效执行的请求拒绝不重试

**目标**：输入超长或请求契约不合法时，一次失败即停止当前调用路径，保留事实等待条件修正。

主要位置：`opc/adapters/codex.py`、`dsh.py` 的现有错误分类，以及 `opc/core/engine.py` 对 expert/designer 调用失败的处理。

实施内容：

1. 将明确的输入上限/request schema 拒绝映射到已有阻塞通路，保留 worker 原始信息和实际 token/耗时。
2. expert 与 designer 同样处理；不继续相同请求、不让后续 attempt 被耗尽。
3. 保留模型实际执行失败、计划格式错误、领域失败与环境失败的区别；不新增错误恢复角色、重试框架或自动裁剪策略。

删除/替代：已知不合法请求在条件未变化时仍进入下一轮的路径。

验收：

- A10：模拟 provider 拒绝并计数，包含有 thread ID 但尚未有效执行的情形；首次拒绝后 run=blocked，无第二次相同调用。
- 对照合法请求后返回格式错误、designer 实现失败及普通领域失败，避免一律判为请求错误。
- 修正外部条件后使用已有恢复路径，历史失败和费用不丢失；不虚构缺失的 token。
- 运行 `test_codex_and_config.py`、`test_dsh_worker.py`、`test_engine.py` 和相关研究循环测试。

完成记录：2026-10-27，T5 独立提交（本提交）。Codex/DSH 将无有效执行的上下文上限与请求 schema 拒绝接入既有 infra/blocked 路径；保留真实成本和错误，不新增重试。原受影响套件通过，新增有 thread/session 的 expert/designer 拒绝计数及执行后错误分类对照；适配器套件 53 项通过。

## T6：全链路回归、工程任务对照与文档收口

**目标**：确认前五票组合成一个简化流程，执行一组真实模型工程交付对照并明确结论边界。

主要位置：现有 `opc/tests/`、`tools/tests/`，`README.md`、`opc/README.md`、`opc/scaffold/ONBOARDING.md`、`skills/archa-task/`、`skills/archa-loop/` 与当前 CLI 帮助；仅在必要处更新既有当前设计入口。

实施内容：

1. 用一个离线开发场景串起直接简报、无 objective、失败基线、两步积累、恢复、版本选择、终验和补审阅证据；复用临时 Git/worker 夹具。
2. 用既有数值优化场景确认约束、噪声、工具链变化、冠军、未涨分候选续用、fresh 测量以及旧记录读取没有回退。
3. 检查实际 CLI/技能描述与实现一致，移除“target 达到即停止”“必须有冠军才能交付”等旧主张；历史报告保持历史事实。
4. 对照 spec §2/§5，检查没有新增角色、控制器、运行产物类型和额外模型调用；新语义已替代旧职责，没有并行保留两套主流程。
5. 按 [validation](validation.md) 运行已自检的 DMA 背压工程任务：同一基线、相同需求与模型，直接 Codex / ArcHa 各一次，终点锁定后统一外置验收及匿名审阅；复用其中两组执行指令，不人工代写产品或拆分实现路线。
6. 退役已跟踪的旧 `benchmarks/` 用例/脚本和 `deliverables/fp32-reduce-benchmark/` 包，清理当前入口及专用于退役工具的测试。保留仍验证框架语义的 opc/tools 测试；不删除未跟踪原始运行数据，不新建 legacy 副本。
7. 在本清单记录全套测试、CI 平台结果、输入体积/调用次数、paired pilot 的质量/成本/人工干预及未验证边界，按 validation 的表格填写，不创建重复验证报告。

验收：

- A1–A12 均有对应通过证据；执行 `python -m pytest -q`、`git diff --check`，核对现有 CI。
- 报告明确区分 selected version、champion、停止原因和完成事实；缺证据的任务不能因为改了报告词语而被验收。
- 素材自检和 A1–A12 通过后，执行一次 paired pilot，完整保留两组实际结果与成本。ArcHa 必须满足任务全部完成条件才能说案例可行性通过；不要求它必须比直接 Codex 更快/便宜，不用一轮结果声称普遍增益。
- 若模型服务/CLI 不可用或产品终验失败，其他可执行的代码工作仍完成，T6 保持 blocked 并区分代码验收与真实任务未通过，不声称整体验收完成。首次失败不得被静默修复重跑覆盖；再开展真实试验需新的明确预算。
- 所有 ticket 完成记录已更新，PR 标题和描述反映最终变更、验证及限制；不自动合并 PR。

完成记录：2026-10-27，T6 独立提交（本提交），**离线实现与回归完成，真实任务验收 blocked**。

- 独立提交：T1 `dff6766`；T2 `c1b62b1`；T3 `615434b`；T4 `90ea774`；T5 `8291fde`；T6 `8cc47ba`；最终外部阻塞记录见本提交。T4 额外受影响套件 88 passed。
- 素材自检：`python -m unittest discover -s tools/tests -p test_dma_task_materials.py -v`，8 passed（独立于框架回归）。固定 82 输入；起始版本外置验收 exit 1，57 个失败条目，符合未实现功能预期。
- 输入 SHA-256：`a7ec9936bec02571e25e585fc545989a894d45c018675207530882b4c127af05`；验收器 SHA-256：`e6bf9ea0d5995cd00ce439a6d0706fea1e971c4c1eb73340b8bd937ce38a7dc9`。原件在 `.tmp/dma-validation/`。
- Linux：Debian 13.6 x86_64 / Python 3.12.14，`python -m pytest -q -rs`：215 passed、5 skipped、12 subtests passed（32.12 秒）；5 个跳过均为 Windows 专属探针。`git diff --check` 通过。Windows 本地未运行；现有 CI matrix 为 Ubuntu/Windows × Python 3.10/3.12/3.14，GitHub GraphQL/REST 均返回 Forbidden，无法读取实际 CI 结果，不声称 Windows 通过。
- A1–A4：`test_work_versions_resume_and_select`、`test_failed_work_does_not_advance`、`test_development_local_steps_and_explicit_measurement`。A3/A5–A7：selected delivery、review evidence reuse、environment invalidation、nonchampion measurement 及 missing-evidence 反例。A8/A9：2,156 机器字段、1,000 cases、15 轮历史；默认 history≤12，旧 a1 仍可选；完整数据保留，最终实测 expert prompt 1,818 字符、context.json 32,575 字节、单个完整 evaluation.json 205,304 字节（12 行 history、11 个近期候选）；未把 2,156 机器字段逐项注入。A10：两种适配器的请求拒绝计数测试；A11：原数值优化/噪声/约束/工具链/fresh 测量测试；A12：直接 brief 来源、合同接入与端到端恢复/交付测试。
- 增补 `requirements[].gates`，明确复用冻结门 ID 对需求的覆盖；未知门在 check 报错。没有 check、门覆盖或有效 review 的要求不自动完成。数值 target 仍为信息，显式 requirements/约束负责必要验收。
- 单循环/角色/命令边界保留；新增语义仅写入原合同、plan、ledger 事件和报告。未新增运行产物类型或强制模型调用。param_search 从已有冠军对应 plan 参数恢复，不依赖其仍在近期窗口中。
- 退役已跟踪 `benchmarks` 用例/执行脚本/专用测试及 FP32 评测目录与打包 tar；保留 `benchmarks/reports` 历史和框架测试，不删除未跟踪实验数据。

真实 pilot 记录（未形成可比较产品结果）：

| 记录项 | direct | archa |
| --- | --- | --- |
| 随机先后顺序 | 第 1 组 | 第 2 组，因共同 CLI 阻塞未启动 |
| 同一起始 commit | `94261194c4cf6f2a7f59a216d61d240c30e657a4` | 同左 |
| 模型 / CLI / Python | 请求 gpt-6.1-sol / medium；Codex 0.163.0；Python 3.12.14 | 计划相同，未调用 |
| 开发结果 | 初始沙箱初始化失败；提升权限后建立 thread，但模型代理 HTTP CONNECT 403，无有效模型/产品执行，工作区无修改 | not_run |
| 终点 / 产品正确性 | 仍为起始版本；其失败只作为已知负向控制，不算模型终验 | 无模型成果，不执行产品终验 |
| 开发墙钟 / token | 首次启动 0.114 秒；提升权限后的网络尝试约 45 秒，被确认拒绝后终止；input/output/cached token 未报告，未知 | not_run / 未测量 |
| 共享准备 | 两个独立 Git 起点复制约 0.028 秒，素材检查单列 | 同左 |
| 人工干预 | 无产品代写；CLI 路径覆盖排障及提升权限启动；没有产品修复 | 无产品干预 |
| 正式模型评价 / reviewer | 0 次有效模型调用；独立 reviewer not_run | not_run |
| 外部阻塞 | 默认沙箱创建 installation_id 返回 EROFS；提升权限后解决启动，但 chatgpt.com 模型 WebSocket/HTTPS 代理返回 HTTP CONNECT 403；不是产品错误 | 同一 CLI 前置条件不可用 |

原始现场：`/tmp/archa-dma-pilot/record.json`、`direct-session.jsonl`、`direct-stderr.txt`、`direct-startup2-stderr.txt`、`startup-files.txt`。登录状态为 Logged in using ChatGPT；不复制凭据、不改全局技能/其他项目 runtime。初始两次沙箱内尝试均在 app-server 初始化阶段失败；随后提升执行权限成功建立 thread，但 `wss://chatgpt.com/backend-api/codex/responses` 被代理 403 拒绝，HTTPS fallback 亦无模型响应。约 45 秒后主动终止本任务进程，避免无效重连。有效模型/工具执行为零，item.completed 中只有传输错误；usage 未报告，不能按零计费。没有调换模型、泄露参考答案或偷偷重跑产品试验。

**整体验收未完成**：需提供可用的 Codex 运行目录权限及允许模型连接的网络路由，才能执行已授权的一组真实开发/外置终验/盲审；当前不能下案例可行性或框架增益结论。PR 保持当前审阅状态，不请求合并或自动标 ready。PR/CI API 返回 Forbidden，Git push 通道正常；最终 PR 元数据更新结果见交付记录。

交付记录：Git push 已将 T1–T5 更新到原 PR #5 分支；T6 完成本提交后同样推送。PR 查询经 GraphQL 和 REST（含提升执行权限的读请求）均 Forbidden，实际 CI 未知；不将本地 Linux 结果代替 Windows/远端 CI。PR 元数据 PATCH 已实际尝试，同样返回 Forbidden；标题/描述未能更新，未标 ready、未合并。拟更新正文保存在 `.tmp/pr5-description.md`。最终实现 `8cc47ba` 已成功推送，待本记录提交后一并同步。
