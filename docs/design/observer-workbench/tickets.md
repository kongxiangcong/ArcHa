# 只读观察工作台实施清单

依据：本目录 spec 1.0、prototype.html、development-prompt.md。开发分支：`codex/observer-workbench`；源码基点 `49ba90a`，设计材料提交 `4a4e345`。2026-10-28 开工。

## 产品与设计约定

使用 [editorial-ui 1.1.0](https://github.com/kongxiangcong/skills/blob/main/editorial-ui/SKILL.md)，主模式 **Integrate / visual_policy: preserve**。业务合同和原型为产品依据；技能提供阅读层次、语义样式、焦点、错误恢复和验收方法，不替换原型为其他主题。保留五阶段、常驻完成条件和 1.45:1 内容/详情双栏；窄屏单列。目标视口 1440×900、390×844。产品样式变量与短暂颜色过渡统一在 `web/src/styles.css`，减少动画时关闭过渡；无进度或存活动画。主任务是选择任务、run、轮次并阅读证据。无控制、聊天发送、模型调用和部署。

已读取技能的 implementation-modes、layout-patterns、visual-language、interaction-contracts、motion-guidelines、quality-gates、delivery-template。仅采用工作流原则，不复制其主题或 starter。实际浏览器验证前仅声称源码核查。

## 覆盖与状态

| Ticket | 目标 | 依赖 | 决定 / 规范 | 验收 | 状态 |
| --- | --- | --- | --- | --- | --- |
| O1 | 观察 DTO、只读 adapter 与真实格式离线夹具 | 无 | D5–D8、§4–5、R8–R10 | A01–A03、A12–A14 | resolved |
| O2 | 关联、历史状态与用量及九组 GET 接口 | O1 | D1、D3、R5–R6、R9、R11–R12、§6 | A02–A03、A06–A10、A13–A14 | resolved |
| O3 | 原型白板、地图、任务/run/revision 导航 | O2 | D2、D4、R1–R3、R7 | A01、A04–A05、A15 | resolved |
| O4 | 产物、Markdown、表格、只读调用 | O3 | D1、R3–R6、R10 | A04–A09、A14–A15 | resolved |
| O5 | 刷新、分页、错误滞后与选择保持 | O2–O4 | D3、R3、R9、R11–R12 | A05、A08、A10–A11、A13 | resolved |
| O6 | 包装安装、浏览器验收、回归与使用说明 | O1–O5 | D7–D8、R7、§9–10 | A12、A15–A16，全矩阵收口 | in_progress |

每票只有通过相应验证后才改 resolved；限制和未跑项在下方保留。全部 D1–D8 和 A01–A16 均由上表覆盖。无需新增业务文件、控制路由、模型密钥、外部平台或新的执行语义。

## O1 — 观察合同与来源

范围：`opc/observer/` 模型、只读 SQLite/文件读取、来源身份与路径边界、demo fixture；`opc/tests/` 对应测试。读取真实现有格式，保持冻结版本、明确关系和缺失原因。前置：无。
验证：读取 map/直接/brief/未关联；旧 revision 不串新目标；`mode=ro` 不建库；合法外置根和越界 symlink；源业务文件/数据库不变。
实际结果：`7458f5a` 实现；`opc/tests/test_observer.py` 44 项 PASS（隔离测试环境，源格式夹具）。含只读业务文件/数据库、路径边界、WAL 并发、历史 digest 与 brief 关联冲突验证。

## O2 — 投影与 HTTP

范围：稳定 DTO/关联、preparation/execution/acceptance 分离、要求/指标/用量、全部 GET API、只读调用消息。前置 O1。不触发 Engine/Ledger/执行器。
验证：API 合同、终验归属、未知 USD、分页身份、Codex/DSH 隔离、未知 provider 事件、错误响应与无写路由。
实际结果：全部九组 GET、Pydantic DTO 与生成 OpenAPI、统一错误、分页/日志身份、历史合同与用量投影已实现。44 项后端测试 PASS；真实浏览器来源刷新链 PASS。

## O3 — 白板与入口

范围：唯一 `web/` React/TS/Vite 应用，原型布局、React Flow + Dagre、文本等价任务选择、revision/run/phase/attempt 深链接。前置 O2。
验证：类型检查/构建，浏览任务→run→阶段→轮次；两种视口；键盘可达；全部未知有文字解释。无背景追赶、统计首页和控制按钮。
实际结果：React/TypeScript/Vite 白板与 React Flow + Dagre 已实现，原型层次保留。实际 Chromium 1440×900 / 390×844 截图已查看，未发现整页横向溢出；Tab/Enter 与减少动画 PASS。

## O4 — 证据阅读

范围：TanStack Table 要求/指标，安全 Markdown 与产物要点/原文/下载，assistant-ui 只读调用 primitives。前置 O3。
验证：文件与账本分开；HTML/脚本不执行、图片不自动请求；工具卡重挂载零执行；真实已有数值与证据范围；缺内容可读降级。
实际结果：已接 TanStack Table、react-markdown + remark-gfm、assistant-ui 0.15.31。实际工具卡展开/重挂载、Codex/DSH 内容隔离、产物要点/原文、要求筛选/排序 PASS。只读 Provider 需 Viewport 和空 Tools/DataRenderers 作用域；无工具定义、执行回调或聊天运行时。

## O5 — 持续观察

范围：所选 run/call 2 秒轮询、按 ID 更新去重、深链接保持与取消旧请求、分页内容、错误滞后与恢复。前置 O2–O4。
验证：fixture 写入器追加/半行/替换/截断，旧调用不串新调用；历史轮次不自动跳转；请求错误后保留数据和读取时间并可恢复。
实际结果：所选 run/attempt/call 2 秒轮询，默认选择写入 URL，深链接刷新和历史版本错配回归 PASS。增量写入未强制跳轮次，503 保留旧内容并显示滞后、恢复后保留选择 PASS；JSONL 半行/截断/覆盖由后端测试覆盖。

## O6 — 可交付安装与验收

范围：Python observer extra、静态打包、demo/project 独立入口、现有 README 使用与升级适配说明、浏览器脚本与截图。前置 O1–O5。
验证：干净 checkout 安装/构建/启动；核心无 extra 仍可用；相关回归/类型构建；A01–A16 证据汇总。实测平台 Linux/Chromium；Windows/WSL、真实用户运行包需明确未验证。
实际结果：前端类型检查/生产构建 PASS。README 包含安装、演示、真实项目和升级适配说明。隔离环境安装声明精确依赖 PASS；wheel 与干净归档验证中。

## 当前验证证据

- `npm --prefix web run build`：PASS，TypeScript 与 Vite 生产构建；锁定包见 `web/package-lock.json`。
- `work/observer-test-venv/bin/python -m pytest opc/tests/test_observer.py -q`：44 PASS（亦已在声明版本 FastAPI 0.119.1 / Uvicorn 0.38.0 / Pydantic 2.12.3 下复验）。
- `python tools/observer_browser_smoke.py`：12 个端到端检查 PASS，Chromium；源码材料为合成当前格式，非真实模型运行。覆盖任务/轮次/原文/调用、深链接、版本差异、追加更新、HTTP 失败恢复、两种视口、真实 Tab/Enter、减少动画、放大文本、无外部/写请求及业务文件不变。截图与 JSON 位于 `work/observer-browser/`，为本地验证产物，不是业务数据。
- 原型样式按产品 spec 迁移；技能未引入额外主题、starter、字体资产或运行时依赖。色彩角色集中 `web/src/styles.css`；触发仅 hover/selection 的颜色过渡，120ms，可立即反转，减少动画时完全关闭；无位置动画或自动滚动。
- 原型依据为本仓库 `4a4e345:docs/design/observer-workbench/prototype.html`。技能远程 `SKILL.md` blob `ded63c1cad9970e99dbb9f2c61e30899c2a87189`（1.1.0）；只采纳已读工作流，不声称审计整个技能仓库。
- 未验证：用户真实运行包、Windows/WSL 实机、非 Chromium 浏览器、屏幕阅读器与 OS 原生 IME。当前界面无输入发送/模态/splitter/流式自动跟随，这些控件测试 NOT_APPLICABLE。

- 最终 `work/observer-clean-venv/bin/python -m pytest opc/tests/test_observer.py -q`：44 PASS（3.08s）；完整 `opc/tests tools/tests` 回归在最终新增两个配置投影测试前为 263 PASS / 5 SKIP / 12 subtests PASS（34.22s）。跳过项来自现有测试的平台/可用性条件；无真实模型/设备试验。
- 最终 `work/observer-clean-venv/bin/python tools/observer_browser_smoke.py`：12 PASS；新增相对任务/证据链接、raw HTML 不执行/外部图片零请求、大文件分页后截短自动回到 offset 0；生产 CSP 保持生效。配置合同显式标为必要字段投影，无 workers/环境配置原件下载。原件与投影不混称。
- 独立审查原始问题均已修复：历史 digest 冲突不套目标、URL 默认选择稳定、已选 run 始终在选择器、内容版本/截断重读、成功响应内的滞后提示、安全相对链接、SourceRef 形状和结构不兼容统一错误。每项以对应源码/测试复验，未将静态审查当作浏览器通过。
