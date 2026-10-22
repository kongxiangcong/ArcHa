# 实验提交摘要：<submission_id>

> 起草者：设计 agent；生成时点：执行完成或失败，并冻结本次提交之后。
> 来源权威：`submission.json`、不可变 manifest、原始输出与环境记录。
> 关联 JSON：同目录 `submission.json`（`opc.submission.v0.2`）、`manifest.json`；本摘要不是接纳结论。
> 保存位置：`<artifact-root>/<project_id>/<task_id>/<run_id>/attempts/a000001/submissions/<submission_id>/SUMMARY.md`。

## 绑定

- project_id / task_id / task_revision / task_spec_sha256：<值>。
- run_id / attempt_id / plan_id / submission_id：<值>。
- producer_call_id：<服务登记的调用标识，不以自由文本证明作者身份>。
- manifest_sha256：<冻结清单摘要>；environment_ref：<环境 ArtifactRef>。
- artifacts：<每项 URI、sha256、size_bytes、media_type、producer_job_id>。

## 预期产物对应：artifact_bindings

每个计划中的 `expected_artifact_id` 必须在此明确列为 present 或 missing；ID 来自 TaskSpec 的 `must_haves.artifacts`。

| artifact_id | status | artifact_ref | reason |
| --- | --- | --- | --- |
| <kernel 等既有 ID> | missing | null | <尚未产生或执行失败的具体原因> |

present 必须引用本提交 `artifacts` 列表中的具体原件；missing 保留原因，不伪造空产物。需求标 pass 时，其全部必需产物都必须有 present 绑定，且所需行为检查已经验证。总体报告不能替代 kernel、runner 等各自的产物映射。

## 本轮结果

- 做了什么：<相对计划与基线的实际变更>。
- 测到了什么：<数值、单位、对照、波动、输入条件；链接原始证据>。
- 没测到什么：<未执行、运行失败、工具缺失与证据范围>。
- deviations：<相对计划的偏离、原因与影响；无则空列表>。
- failed_checks / limitations：<失败检查与解释边界，不省略不利结果>。

## 逐项覆盖：coverage

本 TaskSpec 的每个 requirement_id 恰好一行；并非只列本轮计划选中的需求。

| requirement_id | status | check | verified_check_ids | evidence | human_judgment | limitation |
| --- | --- | --- | --- | --- | --- | --- |
| <ID> | unverified | <需验证的行为> | [] | <ArtifactRef 或空列表> | false | <文件存在，但尚未执行行为检查> |

`pass` 需要本需求全部 observable/key-link 检查及非空证据；不能用“代码已写”替代。
`fail` 为检查失败，`partial` 为只完成部分验证，`unverified` 为尚无行为结论，`needs_human` 为仍需人的判断。
`verified_check_ids` 只填真正验证过的既有检查 ID；`human_judgment=true` 表示仍有人工判断未解决，不能同时标 pass。

## 可供审核的主张：claims

| statement | conditions | evidence | level |
| --- | --- | --- | --- |
| <有限条件下成立的主张> | <输入、平台、规模> | <原始 ArtifactRef> | <functional / analytical / simulation / synthesis / hardware> |

仿真证据不能上升为硬件实测；自报改善不等于独立审核已接受。

## 对后续工作的影响

- provides：<本提交提供的接口、结论或可复用结果>。
- affects：<可能受影响的模块与下游任务>。
- 建议下一轮调查：<由现有结果推导；是否执行由专家的新 Plan 和服务门禁决定>。

独立验证 agent 从冻结提交复核；若原件改变，必须形成新提交并重新审核。
