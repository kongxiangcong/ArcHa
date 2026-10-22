# 任务上下文：<task_id> / r0001

> 起草者：Ge；生成时点：形成或修订 TaskSpec，交给专家 agent 之前。
> 来源权威：用户材料与已确认决定；本文件整理上下文，不另发运行指令。
> 关联 JSON：同目录 `task.json.context`、`inputs`、`research_unknowns`、`open_decisions`。
> 保存位置：`.opc/tasks/<task_id>/revisions/r0001/CONTEXT.md`。

## 绑定

- project_id / component_id / task_id：<值>。
- TaskSpec revision / sha256：<已冻结修订与服务计算摘要>。
- 任务目标与需求：<objective；requirement_id 清单>。
- 来源定位：<task.json.source_requirements；项目 REQUIREMENTS 的对应条目>。

## 已定决定：context.locked

| 决定 | 来源及理由 | 对本任务的约束 |
| --- | --- | --- |
| <用户已定事项> | <来源 URI / locator> | <必须保持的边界> |

更改已定决定需要新的 TaskSpec 修订；不能把实现困难解释为已经获得改需求授权。

## 自主空间：context.delegated

- <专家可选的实验方法、设计 agent 可选的实现细节；以预算和 permissions 为边界>。
- <选择需要记录的依据和预期证据；不扩大到发布、修改评价器或绕过审核>。

## 延后事项：context.deferred

- <本任务不处理的想法及再次考虑的触发条件>。

## 权威阅读材料：context.canonical_refs

| URI / sha256 / locator | 为什么必须读 | 影响哪些 requirement_id |
| --- | --- | --- |
| <固定来源> | <接口 / 已有结论 / 项目规范> | <ID> |

## 未知、依赖与复用

- `research_unknowns`：<需要实验回答的问题，不能当作已知事实>。
- `open_decisions`：<仍需用户或 Ge 明确的决定；说明阻塞哪一步>。
- `inputs`：<已有代码、数据、报告的 SourceRef>。
- `dependencies`：<task_id、task_revision、accepted_submission_id、manifest_sha256、required_interface>。
- 可复用点：<具体模块与版本、接口和已知局限；尚未核验则注明>。

本文件只保留本任务必要上下文；长期决定在项目 DECISIONS 记录，不能靠复制多份文本形成互相矛盾的权威。
