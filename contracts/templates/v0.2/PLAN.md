# 实验计划：<plan_id>

> 起草者：专家 agent；生成时点：每次实验之前，依据任务及上一轮审核。
> 来源权威：已冻结 TaskSpec、已登记证据与审核结论。
> 关联 JSON：同目录 `plan.json`（`opc.plan.v0.2`）；must-haves 的定义来自任务修订 `task.json`。
> 保存位置：`<artifact-root>/<project_id>/<task_id>/<run_id>/attempts/a000001/PLAN.md`。

## 绑定与输入

- project_id / task_id / task_revision / task_spec_sha256：<值>。
- run_id / attempt_id / plan_id：<值；attempt_id 例如 a000001>。
- parent_submission_id：<上一轮提交 ID，首次为 null>。
- evidence_refs：<支持本轮设计的 ArtifactRef；包含失败证据，不能只挑好结果>。
- requirement_ids：<本轮针对的需求 ID；其余需求在提交 coverage 中仍需说明>。

## 本轮要回答什么

- hypothesis：<可证伪的预期及适用条件>。
- competing_explanation：<可能产生相同现象的另一解释>。
- change：<相对基线或上一轮只改变什么>。
- controlled_variables：<保持不变的输入、种子、工具、评价器、环境>。
- falsification：<什么结果足以否定假设；不要只写成功标准>。

## 变更和检查

| requirement_id | TaskSpec check_id / link_id | expected_artifact_ids | 本轮观测与原始证据 |
| --- | --- | --- | --- |
| <ID> | <已有检查 ID> | <已声明 artifact_id> | <数值/行为、输出与失败日志> |

- files_modified：<项目相对路径清单；空列表表示无修改>。
- files_deleted：<显式列出；空列表表示无删除；列出不等于获得删除权限>。
- 依赖：<引用 TaskSpec.dependencies 已接纳接口；本模板不新增运行依赖字段>。
- 产物位置：<expected artifact 的 logical_path 到本 attempt 内实际对象的映射>。

## 测量与成本

`measurement_commands` 使用 argv 数组，不依赖对自然语言命令的猜测。例如：

```json
[["<解释器>", "<脚本>", "<参数>"]]
```

运行目录、环境前提、超时及隔离规则由 adapter 和 TaskSpec 约束提供。
`predicted_model_usd_upper_bound`：<美元数值>；`predicted_wall_seconds`：<秒数>。
执行前服务核验剩余预算、权限、依赖与不可变输入；计划成本预测不是已发生账单。
预计触发的 stop_rules：<引用原合同条目>；异常时保留原始失败结果，交给下一轮解释。
本计划不能自行更改验收口径；需要改口径时由 Ge 形成新修订。
