# 只读观察工作台修复改动清单（2026-10-28）

依据用户上传清单，在 `codex/observer-workbench@5b62cd6` 上实施；修改 7 个已有文件，新增本清单与验收记录。原清单所列真实项目历史结果未在本环境复测。

| 文件 | 本次改动 |
| --- | --- |
| `opc/observer/adapter.py` | `_discover` 归并地图任务同目录双入口且保留地图 ID；`_link_revisions` 兼容合同 `_source`、单行交接与有边界多行列表，规范化比较与来源登记，分离研究任务归属及简报校验；`_run_ref` 保留类型、账本状态、停止原因 |
| `opc/observer/models.py` | TaskRevision 新增 research_task_id、ownership_state、brief_bindings |
| `web/src/types.ts` | 兼容新增合同字段与 run 引用事实 |
| `web/src/App.tsx` | 默认任务概览、未选运行；独立 task=history；任务/合同/run 作用域；范围外显式链接；准备关闭与原始停止原因；任务材料状态；分别展示归属、简报校验、路径和 SHA |
| `opc/tests/test_observer.py` | 新增 10 个测试函数、16 个用例；增强显式绑定只读与摘要变化回归 |
| `tools/observer_browser_smoke.py` | 可选 --chromium；双入口、未关联合同、撤回 preparation 夹具；默认选择与历史范围断言；深链接及原有烟测保留 |
| `docs/design/observer-workbench/spec.md` | 更新发现、绑定、状态语义、DTO 与历史入口规范 |
| `docs/design/observer-workbench/validation-20261028.md` | 本轮实际测试结果、命令、运行环境及真实项目验证限制 |

没有修改引擎、API 路由、前端依赖声明、任务完成 tickets 或用户研究来源。静态前端构建产物由原构建命令生成并被 Git 忽略。历史运行目标仍由自身冻结合同解释。

本轮实际证据见 [验收记录](validation-20261028.md)；不复用上传清单中其他机器的临时证据路径。
