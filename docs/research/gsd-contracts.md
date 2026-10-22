# gsd-core 合同、模板与项目接入核查

核查日期：2026-10-21 至 2026-10-22（Asia/Shanghai）。范围：用户指定的 [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) 官方模板、接入流程与相关确定性校验源码。本文为复用分析，不是 GSD 安装或端到端运行报告。

## 1. 基线与判断

本轮通过 GitHub connector 读取官方仓库，默认分支是 `next`；锁定提交 [`812ddb5feb357ebf702b7f48c3e915a8ce4da384`](https://github.com/open-gsd/gsd-core/commit/812ddb5feb357ebf702b7f48c3e915a8ce4da384)，提交时间 2026-10-21 14:44:49 UTC。[package.json](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/package.json) 版本为 `1.18.0`，[LICENSE](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/LICENSE) 为 MIT。它是核查快照，不声明为今后最新版本。

**值得优化当前 OPC，但应复用可追踪的工件结构与校验思想，不把整套 GSD 主控嵌入 Ge。** 当前 OPC 已有版本、摘要、身份、预算等运行合同；明显缺口是需求 ID、决策分类、计划到需求的映射、关键连接验收与逐项覆盖记录。GSD 在这些方面比当前两张 Markdown 模板具体。

GSD 也并非只有自然语言 skills：模板使用 Markdown + YAML/XML，部分信息被 CLI 确定性处理；本轮读到 onboarding 路由、计划结构检查、覆盖分类与内容指纹失效代码。不过，这些代码不能代替 OPC 的运行身份、独立审核签署、预算账本或外部作业恢复。

## 2. 模板中的可复用结构

以下链接均指向同一固定 SHA，表中“建议”是对 OPC 的设计推断。

| 官方工件 | 实际结构 | 对 OPC 的建议与边界 |
| --- | --- | --- |
| [PROJECT](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/project.md) | 项目身份、核心价值、已验证/当前/排除范围、约束与决策 | 新增项目级上下文，与一次 TaskSpec 分开；已有代码推测出的能力标“观察到”，不能自动升级为独立验收完成 |
| [REQUIREMENTS](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/requirements.md) | 稳定 REQ-ID、当前与延后范围、排除理由、需求到 phase 追踪 | 用稳定 ID 连接需求、TaskSpec、Plan、artifact、verification；不要只有自由字符串清单；研究需求允许由多个任务共同覆盖 |
| [SPEC](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/spec.md) | 每项需求有 Current/Target/Acceptance，附边界、edge coverage、must-NOT 禁止项 | 明确基线、目标、证伪/通过条件；加入负向验收，如不可改 evaluator、不可重复外部提交；不采用主观 ambiguity 分数作为执行授权 |
| [CONTEXT](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/context.md) | 已决定事项、可自主取舍、canonical refs、已有代码/复用点、延后想法 | Ge 把用户已决定与 agent 可选实现明确分开；下游只读必要的来源版本，不反复追问已经确定的决定 |
| [PLAN](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/phase-prompt.md) | dependencies、修改/删除文件、requirements、读前材料、动作、验证、完成条件；must_haves 分 truths/artifacts/key_links | 扩展 ExperimentPlan：目标需求、预期可观察事实、产物声明、模块连接检查、依赖与变更范围。不要依赖任务排序推断依赖，也不要用文件存在或代码行数证明行为正确 |
| [VALIDATION](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/VALIDATION.md) | 框架/命令、任务→需求→测试映射、快速与完整检查、缺失测试设施、手工检查原因 | 把测试入口和环境前置条件纳入项目接入配置；按任务成本安排检查，不把固定频率或“Nyquist”名称当科研可靠性保证 |
| [SUMMARY](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/summary.md) | requires/provides/affects、变更、偏离、结果、覆盖条目和后续就绪状态 | Submission 增加逐交付物 coverage 与相依影响；结果包含失败和未知；人读摘要由冻结原件生成，不能自己成为最终接纳 |
| [VERIFICATION](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/verification-report.md) | observable truths、artifact substance、key links、需求覆盖、gap、行为未验、covered files/digest | ReviewDecision 按 requirement/check ID 回报结果；区分“存在”“已接线”“实际行为已测”；不满足项产生 gap/follow-up，而不是只给一句 pass/fail |
| [STATE](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/state.md) / [CONTINUE](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates/continue-here.md) | 小型状态摘要、当前动作、阻塞、决定与接续点 | OPC 的 STATE/HANDOFF 为 ledger 投影与恢复提示，包含 event cursor、未决 job、manifest 引用；不靠一份 Markdown 判定外部实验已经停下或完成 |

需要区分模板用途：PROJECT/CONTEXT 是语义上下文；PLAN/SUMMARY 是结构化交接；VERIFICATION 是结果报告；STATE 是阅读入口。它们不应在 OPC 中各自维护一份可互相冲突的 `accepted`。

## 3. 确定性源码核查

### 3.1 项目接入不是直接复制模板

[onboard-projection.cts](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/src/onboard-projection.cts#L246-L319) 的 `nextAction` 根据现有代码、codebase map、现存规划工件、既有规范和 onboarding summary 选择下一动作。已有部分规划文件却不完整时走 `partial-planning`，不悄悄重新初始化。对应 [onboard workflow](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/workflows/onboard.md) 明确把流程呈现与确定性路由分开。

可迁移顺序：识别目标项目根与已有状态 → 只读盘点源码/测试/规范 → 导入已有文档引用 → 填接入配置 → preflight → 最小任务。项目缺项要报缺项；已有数据不覆盖。GSD 的七份 codebase map 是其约定，OPC 首版可缩成一个有版本与证据定位的项目映射，按项目复杂度再拆。

### 3.2 计划结构有实际检查，结构通过仍非结果正确

[verify.cts](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/src/verify.cts#L1330-L1450) 检查必要 frontmatter、任务结构、截断文件、checkpoint 与 autonomy 一致性等。部分检查产生错误，部分只产生 warning；“有模板字段”不等于所有语义都受强制保障。

[Requirements Coverage Gate 说明](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/docs/features/requirements-coverage-gate.md) 要求阶段需求至少被一个计划覆盖。本轮读了该官方说明，未复现它的完整运行路径；OPC 应把覆盖关系直接落实成可测试的校验：引用必须存在、没有漏掉 required 项、不能靠重复条目充数。

### 3.3 覆盖分类器不能认证测试结果

[coverage.cts](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/src/coverage.cts#L292-L375) 检查条目唯一 ID、描述、严格布尔值、验证类型/ref/status；只有 `human_judgment === false`、验证列表非空、每条为 pass 且无结构错误时才自动分类通过。空列表不会因 `every()` 的空真值被放行，这是值得复用的具体门禁。

但该函数是在分类 SUMMARY 自报元数据，没有在这里执行测试、检查原始 stdout/exit code 或认证 reviewer。因此 OPC 的 `coverage.status=pass` 必须关联已冻结证据和服务登记的 review；不能把复制来的 pass 字符串当凭据。对于真正需要人的判断保留原因，其余缺证据先交回工作流补证，不必机械地把所有未知转成人工操作。

### 3.4 内容变化必须使旧审核失效

[verification.cts](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/src/verification.cts#L1936-L2078) 重新计算 covered digest；声明指纹但缺字段或格式不对会进入 stale。v3 把声明覆盖集合与当前 phase 工件合并计算，避免审核后新增计划/摘要却不触发失效。没有指纹的旧报告仍走兼容的 mtime 检查。

OPC 应保留已经设计的更强 manifest+身份绑定，并覆盖所有用于结论的代码、输入、评价器、环境和主张。生产合同不引入“缺 manifest 就降级到时间戳”的兼容放行；新快照必须新审核。可借用 GSD 对新增工件、缺失/不可读与陈旧状态的处理思想，不必复刻其全部文件解析代码。

### 3.5 只允许一个判定来源

[ADR-5057](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/docs/adr/5057-one-owner-per-workflow-verdict.md) 记录过多个状态推导点对同一陈旧验证报告给出不同结论的问题；这支持 OPC 已有的“接纳服务单一权威”方向。[state-md-schema.cts](https://github.com/open-gsd/gsd-core/blob/812ddb5feb357ebf702b7f48c3e915a8ce4da384/src/state-md-schema.cts) 与 STATE 模板使用一个字段声明源生成派生内容。OPC 也应从 Pydantic/schema 生成表单和模板字段，减少人读与机器合同漂移。

## 4. 到当前 OPC 的具体改进映射

以下是建议的新合同设计；是否已经实现，以仓库当前模型和本轮校验报告为准。

| 当前缺口 | 建议补充 | 确定性检查 |
| --- | --- | --- |
| 每次任务没有统一项目接入对象 | `ProjectConfig`：稳定 project_id、repo/root绑定、adapter、读写与冻结路径、工具入口、artifact/workspace布局、输入资产引用 | ID/版本有效、路径不逃逸、配置根不依赖调用 cwd、命令 argv 与工作目录明确；模板不触发命令 |
| TaskSpec 只有字符串 deliverables / hard_gates | `requirements[]`：requirement_id、statement、source、scope/current-target、acceptance check IDs | ID 唯一；required requirement 有明确 check；延期与排除项不计入完成分母 |
| 已定决策与实验自主空间混杂 | `decisions`、`discretion`、`deferred`、canonical_refs | 变更 locked decision 要形成合同新版本；研究未知保持未知，不伪装用户授权 |
| Plan 只声明 expected_artifacts 字符串 | `requirement_ids`、`must_haves`/结构化 checks、`files_modified`、`files_deleted`、依赖和产物声明 | 需求引用存在；修改范围受项目权限与任务范围共同约束；禁止删除没有授权的路径 |
| 缺模块之间的真实连接验收 | `key_links` / integration checks：from/to、连接合同、如何触发、预期行为、命令/证据 | 文件存在、接口声明与真实调用分开；编译→模拟、请求→DRAM 等连接须行为证据 |
| Submission 主张难反查需求 | `coverage`：requirement/check/artifact IDs、observed status、evidence refs、deviations、依赖影响 | pass 必须有非空证据；未跑/不适用/失败显式区分；作者记录不等于接纳 |
| Review 只有整轴 verdict | 各 check 的结果、gaps、behavior_unverified、复算记录、可接纳的条件范围 | 两轴仍独立；必需check缺失/unknown不能accept；内容与身份绑定仍必须成立 |
| 新会话要翻长日志 | 状态与交接摘要、必要上下文索引 | 派生视图带 event cursor；恢复先对账再执行；不删除历史证据 |

最优先的是 **REQ → Plan → Artifact → Check → Review** 这条可追踪链，再补项目配置。不要在首版复制全部 UI、安全、商业、用户画像或每种 phase 模板；领域独有项放 adapter extension。

## 5. 不直接照搬的规则

- GSD 的某些模板把 commit/ship 纳入完成流程；OPC 不能因套模板获得 commit/push/PR/部署授权。
- requirements 模板规定每项需求映射一个 phase，OPC 可有多模块共同满足一个需求，最终由联合证据接纳；不能为满足模板强拆假需求。
- PLAN 的 `wave` 是预先排程；OPC 的科研循环应基于依赖与当前反馈动态选择，不把数字排序当依赖。
- `min_lines`、`contains`、正则 wiring 是静态线索，不足以证明编译/仿真或取消恢复的行为；OPC 应保留独立执行证据。
- `summary.actuals.tokens` 的模板说明是 diff 字符数近似，不是 provider token 账单；不得填进 OPC 模型费用账本。
- CONTINUE 模板指导恢复后删除临时交接文件；OPC 可生成新交接版本或归档，但不因此删除失败与原始证据。
- GSD README 的跨运行时安装器与全局 agent 规则不需要随 OPC 项目接入；本轮没有安装 GSD，没有运行上游脚本。

## 6. 复用与许可方式

本轮建议采用结构和校验思想，使用 OPC 自己的中文模板与严格模型，未复制整份 GSD 模板或代码。后续若实际复制/修改其代码或模板的实质部分，应随分发保留 MIT 版权及许可证，并记录固定来源 SHA。用户指定 GSD 为参考不意味着必须安装第二个项目调度器。

安装资料还存在版本漂移例子：固定 package 声明 Node `>=24`，接入教程仍写 Node 18；本轮未尝试安装，不能据教程宣称兼容。此处只是记录源码/文档差异，OPC 不需要依赖 GSD runtime 才能采用上述结构。

可得到的结论：GSD 可以显著改善 OPC 的语义合同、需求追踪和接续材料；可靠执行仍需要 OPC 的 schema+状态机+身份/预算/job/manifest机制。参考模板的目标是让每一轮更清楚、可查、可检验，而不是让项目多出一套无人维护的文档树。
