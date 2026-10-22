# 接续摘要：<project_id> / <task_id> / <run_id>

> 起草者：Ge 或恢复服务；生成时点：跨会话接续、暂停或需要明确恢复点时。
> 来源权威：运行账本、服务作业登记与不可变 JSON；本文件仅为可重建投影。
> 关联 JSON：当前 task / plan / submission / decision 的精确 URI 与摘要。
> 保存位置：`<artifact-root>/<project_id>/<task_id>/<run_id>/views/HANDOFF.md`。

## 投影时点

- generated_at：<UTC 时间>。
- ledger_uri / event_cursor：<账本引用与最后消费事件位置>。
- state_as_of_cursor：<账本派生状态；不是可手动写入的指令>。
- task_revision / task_spec_sha256：<正在使用的冻结任务修订>。
- projector_version：<生成器版本；没有生成器时注明人工整理，需重新对账>。

## 必须先读的材料

| 工件 | URI / 摘要 | 用途 |
| --- | --- | --- |
| task.json 与 CONTEXT.md | <值> | 目标、权限、预算、已定决定 |
| 最近 plan.json | <值或尚未生成> | 本轮假设与执行边界 |
| 最近 submission.json / manifest.json | <值或尚未提交> | 已冻结产物与主张 |
| 最近 decision.json | <值或尚未审核> | 已发现缺口与可接受结论 |

## 未完成动作

| job_id / call_id | 幂等键或服务登记引用 | 最后已知状态 | 下一步先核查什么 |
| --- | --- | --- | --- |
| <值> | <值；不含凭据> | <截至 cursor 的观察> | <查询当前服务状态 / 回收已完成输出> |

存在未决外部作业时先对账，不能直接重复提交；“暂停”“无输出”不证明远端作业已经停止。
预算消耗与余额从账本读取；不要按 Markdown 中的旧数值继续运行。

## 接续决策

- 已被服务接纳的结论：<submission / review / manifest 引用；没有则写无>。
- 尚未解决的 gaps / unknowns：<检查 ID、缺什么、由谁处理>。
- 下一项允许的动作：<基于当前状态与权限的建议；执行前重新验证>。
- 阻塞点：<所需输入或外部状态变化；普通失败可继续探索则说明下一实验>。
- 用户已确认决定：<canonical refs；不得要求用户重复确认已有授权>。

本文件不新增 JSON 合同字段，不承载接纳签名，不用来手动推进状态机。
`STATE.md` 若存在也必须由相同账本重建；两份投影不一致时回到账本核查，不任选一份覆盖。
项目内导出本摘要时保留原件 URI、摘要与投影时点；历史实验和失败证据继续保留。
