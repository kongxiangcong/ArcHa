# 01: 通过新 Provider 配置完成 Codex／custom 研究闭环

**What to build:** 研究者通过安装后的 CLI 使用 Codex 或 custom 完成探针提出、实验执行、探针重拟及收尾消化，统一从 stdin 接收任务并以文件交付产物。新配置一次切换，现有工程获得明确的人工迁移路径，研究提交与恢复语义不变。

**Blocked by:** None (can start immediately).

Status: ready-for-agent

**规格：** [Research Workbench 与多 Provider 执行](../spec.md)。本票覆盖 Provider 基础、Codex／custom、配置与安装迁移；DSH 由 02 交付，结构化事件由 04 起交付。本票不以尚未实现的事件文件作为验收前提。

- [x] 从已安装 CLI 完成至少一轮探针与结果提交，默认 Expert、Executor 都使用 Codex；custom 通过真实脚本进程完成同一文件协议。
- [x] 先在本票内整理 Invoker、Provider 与 Process 职责，再完成配置和调用方的一次切换；不新增兼容预设、能力注册表或生产测试接口，不改变 Engine／Workspace 研究语义。
- [x] 新配置直接使用 expert、executor 角色对象，落实父规格中的模型、超时、环境覆盖、Codex 推理强度和 custom argv／占位符规则。非法或不支持的选项在派发前报错，不静默忽略。
- [ ] 移除旧包装、preset、输入／输出模式和 scripted 生产预设；旧格式明确拒绝并给出人工迁移说明。测试与演示改用 custom 或替身 CLI，已安装入口和既有浏览器验收不会依赖被删除的配置。
- [x] 提示词正文仅通过 stdin 传入，超过 128 KiB 可用；临时提示词按调用清理。stdout/stderr 直接写入原始日志，运行期间可通过既有材料入口阅读，不捕获 stdout 作为研究产物。
- [x] Agent／脚本自行写入指定暂存产物，Codex 最终聊天不会覆盖探针、结果或状态草稿，包括输出与状态位置相同的收尾调用。
- [x] 继承宿主环境并叠加显式覆盖，使用无头非交互调用和用户选定权限；不隔离 HOME、不复制凭据，不因权限失败自动放宽权限。
- [x] 四种角色调用均通过新配置执行，重拟与收尾使用 Expert 配置；停止／继续、预算追加、断点重拟和收尾规则保持不变。
- [x] 非零退出、缺失／空产物、非法状态、超时、取消及失败重试残留均不污染已提交材料；日志保留实际失败上下文，进程树退出后没有后代继续写工程。
- [x] 新安装包含全部本票模块，工程配置优先于分发默认配置；显式升级保留现有工程配置和研究材料。人工迁移后的工程能通过已安装 CLI 运行。
- [ ] 复用已部署 CLI、研究轮次、恢复、进程控制与安装测试验证以上行为；原始日志通过现有 HTTP／浏览器链仍可读。只按可观察行为调整测试，不加入最终形态尚未交付的 Trace 断言。


## Answer

- `opc/adapters/providers.py` 负责已验证角色配置与 ProviderRequest → Launch；Invoker 保留产物、stdin 和日志生命周期，Process 保留进程树管理。默认 Codex 使用 JSON 无状态执行，沿用 CLI 权限；custom 仅执行 argv/file 协议。Engine／Workspace 未改动。
- 安装清单包含 Provider 模块；人工迁移说明位于 `opc/README.md#worker-configuration-migration`。既有测试的 scripted 预设已替换为 `opc/tests/worker_fixture.py` 真实脚本进程。
- TDD 首个已安装 CLI 测试先因旧 `roles` 边界失败，切换后通过。专项 `test_topic_cli.py`：52 passed，包含默认／显式 Codex 参数、文件产物不被最终聊天覆盖、超过 128 KiB UTF-8 stdin、环境覆盖、旧配置拒绝、失败与重试；Codex 使用替身可执行文件，未声称真实模型验收。
- HTTP 控制回归：5 passed（2.23 秒）。受限沙箱中 TestClient 卡在 AnyIO portal 启动；退出本次卡住进程后，在允许 HTTP 测试运行的环境验证通过。浏览器脚本和实际浏览器验证由 03 集成，故相关组合检查项暂不勾选。
