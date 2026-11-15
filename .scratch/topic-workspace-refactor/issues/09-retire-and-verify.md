# 09: 完成旧实现退役与全仓交付验收

**What to build:** 用户获得一套从部署、CLI、技能到工作台均可使用的新 ArcHa；旧实现和失效说明被移除，旧研究数据仍保留，完整交付有可重复的验收依据。

**Blocked by:** 06：贯通研究技能与按需报告；08：从工作台停止、继续和追加轮数

**Status:** resolved

依据：[父规格](../spec.md)、[开发方案](../../../archa-refactor-plan.md)、[架构决策](../../../docs/adr/0001-topic-workspace.md)。具体文件清单以开发方案为准。

**范围与归属：** 负责 expand–contract 的最终收缩与全仓集成，不重复建设前八项能力。按开发方案的删除清单逐项确认无消费者后删除，并承接残留调用、包资源、说明和旧测试清理。

- [x] 逐项核对方案第 7 节：旧特定 CLI 适配器、工具边界与拦截脚本、Claim/结果账本、验收与晋升、旧进展模块、契约准备与简报、评价模板和参数扫描均无残留消费者后删除。
- [x] 审查旧领域评价器、旧模型/配置类型及跨模块导入，删除无消费者实现；不得留下只能导入但实际执行失效的旧入口。
- [x] 全部正式 CLI、技能、本地运行时、观察与控制接口使用新协议，撤除开发过渡入口或临时双实现，不承诺旧格式兼容。
- [x] 整合工作台与按需报告服务，所有保留的报告入口使用新整理能力；调用、部署和资源清单相互一致。
- [x] 同步根入口说明、引擎说明、初始化资料、技能说明、包资源和测试夹具；新文档不再指导用户调用已退役流程，旧规格与历史记录的替代标记保留。
- [x] 旧研究数据原位保留，不批量删除或迁移；新运行不会无声恢复旧格式，研究完成不会触发合并或发布。
- [x] 从干净临时目标工程通过本地入口验证初始化、单步、持续运行、停止、人工修改、继续、追加预算、阻塞恢复、只读状态和按需报告，并完成工作台实际操作。
- [x] 核心与工具两组测试完整收集并通过适用回归，前端适用检查及浏览器流程通过；各切片已有测试保留，不把最终验证缩减为导入检查。
- [x] 核对方案第 8 节所有验收边界均有实际验证归属，包含配置错误、非零输出、超时、进程树清理、并发锁、提交中断、末轮收尾与材料阅读。
- [x] 可用真实 CLI 补最小调用并报告环境限制；离线确定性测试仍独立可重复，不以真实模型调用代替自动化验收。


## Answer

完成最终收缩：新实现归入 `core/{engine,workspace}`、`adapters/{worker,prompts}`、`cli`、`log` 和分发 `workers.json`；移除双 CLI、`--topic-runtime` 过渡参数、旧契约/账本/评价/晋升/工具拦截及无消费者类型。部署依赖仅使用单一 allowlist，scaffold 不再隐式导入旧配置。旧测试与浏览器脚本随退役协议移除，保留全部专题切片、部署、历史材料、进程树/锁及 Windows 专属回归。当前 README、平台说明、包资源与 CI 已同步，历史说明保留并标明替代关系，未迁移或删除研究数据。

验收于 Linux / Python 3.12 执行，基于 08 集成提交 `a766faf`：

- 全仓 `pytest --collect-only -q`：96 项完整收集；`pytest -q`：93 passed、3 skipped、12 subtests passed（60.32s）。跳过为 Windows Job 启动失败、batch wrapper 与 8.3 路径用例；依赖库另有一条 anyio 弃用警告。HTTP 用例在授权宿主环境执行，避免外层沙箱 TestClient 挂起。
- CLI 退役回归先证实旧 help 仍显示 onboard/promote 且缺少 resume，再切换正式入口后通过；无 `--topic` 的初始化拒绝执行且不产生 `.opc`。
- `npm --prefix web run build`：TypeScript 类型检查与生产构建通过。`PLAYWRIGHT_BROWSERS_PATH=/tmp/archa-playwright` 下两个真实 Chromium 工具均通过：`observer_browser_smoke.py` 验证实时双流日志、Expert/Executor/收尾、失败/中断、demo、材料导航、HTML/路径边界、只读轮询、主题、移动布局与键盘；`workbench_control_smoke.py` 验证两页竞争、停止/继续、阻塞、追加预算、错误与未知执行、完成不可重开及阅读位置保留。
- 独立安装技能后，从目标工程 `.archa/archa.py` 验证 init/step/run/stop、编辑探针、resume、追加预算、阻塞恢复、只读状态与报告；覆盖来自 `test_topic_*` 和 `tools/tests/test_topic_skills.py`，未借用源树导入。屏蔽 observer 可选依赖的收集仍成功（93 项）；新 HTTP 测试在缺依赖时正常跳过。
- 无网络构建 wheel 成功；在全新仅含标准库的 venv 中解包安装，确认配置和生产静态资源存在、退役模块缺席，并实际通过 init/run/status/report。运行时 manifest 的完整性、可搬迁部署和显式升级回归通过。

方案第 8 节覆盖归属：

| 边界 | 实际验证 |
| --- | --- |
| 配置与输出 | `test_topic_cli`：错误 preset/旧字段/类型/模板、文件/stdout、空白/非零/超时与日志保留 |
| 进程树与登记 | `test_topic_process`、`test_platform`、`test_topic_control`：登记失败、正常退出/父退出/停止后后代清理、崩溃锁释放、未知归属拒绝执行 |
| 工程独占与竞争 | `test_topic_control` 与 `test_workbench_control`：同专题/跨专题、两页面同时恢复、旧 stop 与新执行竞争及重复停止 |
| 提交恢复 | `test_topic_recovery`：准备前后、commit 转入前后、STATE/probe 各替换前后、清理前；继续/完成/阻塞/收尾；只复用已提交结果 |
| 预算、阻塞和上下文 | `test_topic_rounds`：末轮仅消化、完成/预算/阻塞区分、追加及非法降低、否定结果、当前上下文与可选 PIM |
| 人工介入、部署与报告 | `test_topic_cli/control`、`test_topic_skills/research_skills/project_layout`：真实本地入口停止、修改、继续、保留材料与历史副作用，状态只读、按需报告 |
| 工作台与全仓 | 两个真实浏览器工具、完整核心/工具收集回归、生产构建与独立 wheel 验收 |

环境限制如实保留：真实 Codex 参数已按 `codex exec --help` 核实；最小真实调用返回 `failed to initialize in-process app-server client: Read-only file system (os error 30)`，未绕过权限，不能声称真实模型调用成功，详见 [02 验收记录](02-universal-worker.md)。本机不能执行 Windows 专属测试，保留对应回归与 Linux/Windows × Python 3.10/3.12/3.14 CI 矩阵。
