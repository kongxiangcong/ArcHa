# OPC v0.2 人读模板

这些模板由 Ge 和工作流按阶段生成，用户提供已有文档、方向与必要决定即可，不必逐张手填。
字段以 [models_v02.py](../../models_v02.py) 为准；本文模板不是新的运行协议。

## 最少生成什么

首次接入只生成项目说明、需求表与必要 JSON。任务上下文、计划、结果、验证和交接在对应步骤按需生成，空文件不能代表完成步骤。

| 模板 | 起草者 / 生成时点 | 实例位置与关联 JSON |
| --- | --- | --- |
| PROJECT | Ge / 只读盘点项目之后 | `.opc/context/PROJECT.md`；`.opc/project.json` |
| REQUIREMENTS | Ge / 导入用户材料之后 | `.opc/context/REQUIREMENTS.md`；各任务 `task.json.requirements` |
| CONTEXT | Ge / 冻结任务修订时 | `.opc/tasks/<task_id>/revisions/r0001/CONTEXT.md`；同目录 `task.json` |
| PLAN | 专家 agent / 每次实验之前 | attempt 目录 `PLAN.md`；`plan.json` |
| SUMMARY | 设计 agent / 冻结提交之后 | attempt 下 `submissions/<submission_id>/SUMMARY.md`；`submission.json`、`manifest.json` |
| VERIFICATION | 独立验证 agent / 审核冻结提交之后 | attempt 下 `reviews/<review_id>/VERIFICATION.md`；`decision.json`、`Standards.json`、`Spec.json` |
| HANDOFF | Ge 或恢复服务 / 需要跨会话接续时 | run 下 `views/HANDOFF.md`；引用运行账本与已登记 JSON |

这里的 attempt 目录统一指：

```text
<artifact-root>/<project_id>/<task_id>/<run_id>/attempts/a000001/
```

计划、提交、审核的原件只保存在该证据目录（可位于`.opc/local/artifacts`或项目外）。项目内可以显式导出带来源 URI、摘要、时间的阅读摘要，不双写权威副本。`artifact-root` 的机器绝对位置由本地绑定解析，不写入共享合同。

## 权威与修改规则

- PROJECT、REQUIREMENTS、`.opc/context/DECISIONS.md` 是可审阅的项目上下文与决定记录；Ge 提取来源、保留未知，再形成任务修订。
- `.opc/tasks/<task_id>/revisions/r0001/{task.json,TASK.md,CONTEXT.md}` 属于同一修订；`TASK.md` 由 JSON 生成人读视图。已冻结修订改变后生成新修订，不原地偷改。
- 接纳服务使用经过校验、身份绑定和证据核验的运行 JSON；Markdown 中的勾选或“通过”不能改变运行状态。
- `STATE.md` 和 HANDOFF 只是可重建投影，必须标注账本位置与 event cursor；恢复先对账，不以投影推断外部作业已经结束。
- JSON 结构校验只证明字段及关联满足规则；不证明证据真实、执行获授权或审核者独立。

## 一条追踪链

`requirement_id → plan_id → artifact_id → artifact_bindings.artifact_ref / manifest → check_id / link_id → review_id`。
需求 ID、检查 ID、产物 ID 使用模型允许的小写格式，例如 `req-tail-01`。每项运行需求必须有 observable 或 key-link 检查，文件存在本身不够。
SUMMARY 显式列出计划产物到提交原件的绑定；缺失项记录 missing 和原因。pass 需求同时要求其必需产物 present 与行为检查覆盖，不能只提交一份笼统的通过报告。
Submission 与 Review 的 coverage 各列出本 TaskSpec 全部需求且恰好一次。`pass` 表示所需行为检查均有证据；“文件存在但行为未验”记 `unverified`，混合结果记 `partial`，等待人判断记 `needs_human`。
模板不增加 commit、push、PR、部署或改评价器授权；执行范围仍由合同与服务门禁控制。

## 参考来源

这些是 OPC 原创中文结构，参考 [GSD 模板目录](https://github.com/open-gsd/gsd-core/tree/812ddb5feb357ebf702b7f48c3e915a8ce4da384/gsd-core/templates) 的需求、上下文、must-haves、覆盖和交接设计；固定 SHA 为 `812ddb5feb357ebf702b7f48c3e915a8ce4da384`。
核查依据及不采纳项见 [GSD 研究记录](../../../docs/research/gsd-contracts.md)。上游为 MIT，本次未复制整份模板或引入其运行时。
