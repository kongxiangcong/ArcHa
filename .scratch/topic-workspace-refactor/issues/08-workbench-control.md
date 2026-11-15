# 08: 从工作台停止、继续和追加轮数

**What to build:** 用户可以在浏览器停止当前执行、补齐条件后继续专题或追加预算，明确看到控制请求与实际生效的区别，多页面操作也不会重复启动。

**Blocked by:** 07：在工作台查看专题与实时执行

**Status:** resolved

依据：[父规格](../spec.md)、[开发方案](../../../archa-refactor-plan.md)、[架构决策](../../../docs/adr/0001-topic-workspace.md)。具体文件清单以开发方案为准。

**范围与归属：** 负责工作台控制后端与前端交互，复用已经完成的引擎控制和预算能力，不再实现第二套锁、停止或恢复协议。

- [x] 前后端采用一致的专题控制契约，提供停止、继续及必要的追加预算，移除旧暂停与请求历史协议依赖。
- [x] 提交停止请求后显示等待状态，只有进程树已确认结束才显示停止；超时或归属未知如实显示，不把请求接收当作完成。
- [x] 继续使用原专题和已提交结果，BLOCKED 经显式恢复后推进，BUDGET_EXHAUSTED 需追加预算；COMPLETED 不提供自动重开。
- [x] 多个页面或重复点击继续时仅一个执行者；重复停止、旧请求与新启动竞争不破坏新运行或误停其他专题。
- [x] 控制失败保留当前阅读现场并显示可理解原因；页面刷新或断开不隐式停止或重复启动后台任务。
- [x] 浏览器通过真实后端完成运行→停止→继续及追加轮数链路，并覆盖阻塞恢复、预算耗尽、失败、未知执行和已完成专题。
- [x] 研究报告相关界面若保留生成操作，接入 06 提供的新整理能力由 09 做最终整体验证；本项不依赖旧报告服务，也不新增对 06 的虚假阻塞。

## Answer

实现专题 POST `/resume`（可附正整数 `add_rounds`）与 `/stop`（必须携带当前 `execution_id`），只在 `--control` 下启用。继续请求在线程内通过核心 `TopicEngine.lifecycle` 取得工程锁并更新授权后返回 202；执行、进程树确认和清理由核心统一负责。没有新增锁、停止标记、请求历史或恢复协议。旧 ID 停止不会影响新执行。

页面独立显示控制请求处理中、接收结果及服务端实际活动；控制错误不清空专题、轮次或材料阅读。BLOCKED 显式确认继续，预算耗尽需追加轮数，COMPLETED 无重开入口；保留核心失败及未知执行诊断。未新增报告生成 UI。

验证：
- TDD 首个 HTTP 并发测试先因控制路由不存在（405）失败，接入后通过。
- `pytest opc/tests/test_workbench_control.py opc/tests/test_topic_control.py opc/tests/test_topic_rounds.py -q`：17 passed，含真实子进程、双请求争锁、旧停止请求、预算/阻塞/完成、失败日志及未知归属。
- `npm run build --prefix web`、`npm run typecheck --prefix web` 通过。
- `PLAYWRIGHT_BROWSERS_PATH=/tmp/archa-playwright /tmp/archa-results-venv/bin/python tools/workbench_control_smoke.py`：真实 HTTP、浏览器、Worker 子进程通过运行→停止→继续、双页面及刷新不重启、阻塞恢复、追加预算、失败/未知/完成以及阅读现场保持。
- 当前受限沙箱中 TestClient 会挂起；相同测试在授权提升的执行环境约 1 秒通过，浏览器与回归均在该环境运行。未以 mock 替代。
