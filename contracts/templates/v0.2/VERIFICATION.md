# 独立审核：<review_id>

> 起草者：独立验证 agent；生成时点：针对已冻结 Submission 完成审核之后。
> 来源权威：冻结 manifest、TaskSpec、独立复核证据及服务登记的审核身份。
> 关联 JSON：同目录 `decision.json`（`opc.review.v0.2`）、`Standards.json`、`Spec.json`；接纳服务登记最终状态。
> 保存位置：`<artifact-root>/<project_id>/<task_id>/<run_id>/attempts/a000001/reviews/<review_id>/VERIFICATION.md`。

## 审核绑定

- project_id / task_id / task_revision / task_spec_sha256 / run_id：<值>。
- review_id / review_call_id / submission_id：<值>。
- manifest_sha256 / checked_manifest_sha256：<二者必须一致；服务复算，不信任自报>。
- 身份与独立性记录：<服务证据引用；不能靠填写“独立”二字成立>。
- 复核范围和重跑：<实际审查、执行与未执行项目；证据 URI 与摘要>。
- 产物关联复核：<检查 Submission 的 artifact_bindings；计划要求的每个 ID 均有 present/missing 记录，present 引用属于提交原件，声明通过的需求不缺必需产物；再由服务复算原件摘要>。

## 两轴分别判断

| 轴 | verdict | findings | checked_artifacts |
| --- | --- | --- | --- |
| standards | <pass / revise / fail / inconclusive> | <项目规范、代码质量、可复现性问题> | <非空 ArtifactRef 列表> |
| spec | <pass / revise / fail / inconclusive> | <需求、禁止项、实验结论与证据是否匹配> | <非空 ArtifactRef 列表> |

两轴原始报告保留于 `Standards.json` / `Spec.json`；`decision.json` 汇总双轴和逐项覆盖，不另设第二个接纳状态。

## 需求与行为覆盖

本 TaskSpec 每个 requirement_id 恰好一行，独立填写，不照抄生产者的 pass。

| requirement_id | status | check | verified_check_ids | evidence | human_judgment | limitation |
| --- | --- | --- | --- | --- | --- | --- |
| <ID> | unverified | <可观察行为 / 模块连接检查> | [] | <复核证据 ArtifactRef> | false | <未运行的条件> |

- 文件存在、接口有声明、代码看似连接，仅是静态观察；行为未验记 unverified，部分完成记 partial。
- key-link 要核查生产者输出被消费者真实使用，并满足目标行为；不能只用搜索到符号证明连接正确。
- pass 必须覆盖本需求全部 observable/key-link，证据与当前 manifest 对应，且没有未解决人工判断。
- needs_human 必须写明判断内容与原因；普通缺日志或缺测试优先作为工作流补证项。

## 结论和缺口

`recommended_disposition`：<accept / revise / reject / blocked>。
`conclusion`：<这一轮对假设、竞品解释、目标和下一轮的实际意义>。
`gaps`：<具体缺什么、影响哪个 requirement/check、应补何种证据>。
`unknowns`：<现有证据无法回答的问题>。

| accepted_claims.statement | conditions | evidence | level |
| --- | --- | --- | --- |
| <可接受的有限主张> | <适用条件> | <ArtifactRef> | <真实证据层级> |

只有双轴 pass、全部 coverage pass、无 gaps 才能建议 accept；仍须通过身份、权限、预算和证据真实性等服务门禁。
新源码、输入、环境或产物导致 manifest 变化后，本审核不得继续用于接纳新提交。
后续工作形成新 Plan；本审核不改写 TaskSpec，不替设计 agent 修代码后自己宣告通过。
