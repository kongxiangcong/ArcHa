# 07: 在工作台查看专题与实时执行

**What to build:** 用户在浏览器中浏览新专题的认知状态、轮次材料和真实运行活动，调用未结束时也能看到日志，停止后仍能查看现场。

**Blocked by:** 04：停止、人工修改与安全继续；05：按轮数推进探索、处理阻塞并完成收尾

**Status:** resolved

依据：[父规格](../spec.md)、[开发方案](../../../archa-refactor-plan.md)、[架构决策](../../../docs/adr/0001-topic-workspace.md)。具体文件清单以开发方案为准。

**范围与归属：** 负责观察后端、前端 API 客户端与类型、专题/轮次视图、材料阅读、日志展示及新格式 demo。以专题身份替代旧 Run 视图；控制操作在 08 接入。

- [x] 前后端使用一致的新观察契约，专题列表和详情来自新工作区，不为兼容旧 Run/request 历史而制造伪身份或审计记录。
- [x] 仅显示 Expert、Executor 与收尾活动，移除旧角色固定栏目与 designer 分支判断；轮次详情和导航真实可用。
- [x] 展示当前角色、轮次、开始时间、持续时间和流式 stdout/stderr；调用尚未结束时能看到新输出，不解析私有工具事件或猜测模型行为。
- [x] 运行中、停止中、空闲、未知执行与专题状态分开显示，失败和中断保留已有日志，收尾日志与探针生成日志可区分。
- [x] 当前认知状态不冒充历史轮次快照；材料查看与状态轮询不启动、不恢复、不清理任务。
- [x] 文件阅读限制在明确允许的材料根目录，拒绝越界和原始 HTML 执行；引用原件无需复制成重复材料。
- [x] 保留必要的主题、响应式、键盘操作与可访问性行为；尚未接入的新控制不暴露可误触的旧操作。
- [x] 使用同一新格式和接口提供 demo；浏览器测试贯通真实后端与运行子进程，验证角色、实时输出、材料阅读和失败现场，不以虚假活动替代集成。


## Answer

前后端统一为专题契约：`GET /api/observer/v1/topics`、`topics/{slug}`、`materials?path=…&offset=…`。使用真实专题 slug、状态与执行描述，不生成 Run/request 身份；旧角色、私有事件解析、控制入口和相关前端依赖已移除，08 再接入专题控制。

当前 STATE 独立展示，逐轮提供探针、结果、原件链接和 Expert/Executor/收尾日志。日志按字节游标持续读取，超过首屏页仍显示新输出；收尾日志独立保留。实际失败原因以专题运行材料 `.last-error` 保留，由新调用持锁清除，不混入 stdout/stderr 或认知状态。

材料限定在工程原件和选定专题范围，拒绝路径/软链接越界、私有运行文件和未发布 staging；Markdown 不执行原始 HTML，HTML 文件按纯文本阅读。新 demo 直接写新格式文件并走同一接口，不伪造运行活动。

验证：
- TDD 实际红→绿覆盖新 HTTP/浏览器契约、失败原因持久展示、超过 256 KB 的实时日志、新格式 demo、未发布材料边界。
- `npm --prefix web run build` 通过（含 TypeScript）。
- `PLAYWRIGHT_BROWSERS_PATH=/tmp/archa-playwright /tmp/archa-results-venv/bin/python tools/observer_browser_smoke.py` 通过；真实 HTTP、浏览器和 CLI 子进程贯通角色切换、未结束输出、finalize 非零退出、stop 中断、原件阅读、HTML/越界拒绝、只读保留现场以及主题/移动端/键盘。
- `pytest -q opc/tests/test_topic_{cli,rounds,control,process,recovery}.py`：70 passed。
- 基于 f8deef9，完成前已合入 integration 的 8b9de07；旧观察测试及辅助旧冒烟脚本由 09 统一退休。
