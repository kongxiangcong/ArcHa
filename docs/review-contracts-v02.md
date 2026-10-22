# OPC 合同 v0.2 独立审核

日期：2026-10-22。审核者：独立子 agent `research_runtime`；只读实现，负例证据写入 `.tmp/contracts-v02-review/`。

审查范围：`contracts/models_v02.py`、`build_examples_v02.py`、`validate_v02.py`、`V0.2.md`、`templates/v0.2/`、对应样本与 schema。当前目录无 Git 基线，按新增文件完整内容审查；未执行生成器、未改写旧合同或 GEMV 原件，未重复运行全部测试。

## 结论

初审发现 **1 个 P2：预期产物 ID 与实际提交缺少机器映射**。实现者修复后，独立重跑原反例及可通过正例，已关闭。当前未发现其他阻断此版“结构与部分语义合同”交付的 P1/P2。

这不等于生产服务接纳：身份、证据真实性、内容摘要重算、路径 glob 授权、预算和外部作业对账明确未实现，本次未把这些边界误判为合同 validator 的缺陷。独立审核调用共享操作系统权限，不构成安全隔离。

## P2：缺少 Artifact ID 到实际 ArtifactRef 的关联（已关闭）

初审位置：`models_v02.py` 原第 286–301 行的 `SubmissionV02` 和原第 354–355 行的计划产物校验。Plan 列出了 `expected_artifact_ids=[kernel, runner]`，但 Submission 只有无 ID 的 `ArtifactRef[]`；原 `check_bundle()` 仅校验计划 ID 属于任务已声明 ID 集合。

反例把已有样本中的双轴与 coverage 改为全 pass，保留提交仅有 `evidence.json`，便得到 `recommended_disposition=accept` 且 `check_bundle()==[]`。问题不在于没有读取证据文件，而是 schema 根本没有表达 kernel/runner 到实际对象的映射，无法完成声称的 `REQ → Plan → Artifact → Check → Review` 结构追踪。

初审证据：

- `.tmp/contracts-v02-review/audit-probes.json`
- `.tmp/contracts-v02-review/artifact-mapping-submission.json`
- `.tmp/contracts-v02-review/artifact-mapping-review.json`

修复增加 [ArtifactBinding](../contracts/models_v02.py#L286) 和 [跨对象产物检查](../contracts/models_v02.py#L372)：

1. 每个绑定声明 `artifact_id`、`present/missing`、实际引用或缺失理由。
2. 已知 ID、唯一性和计划预期产物均需检查，不能静默漏掉计划产物。
3. present 引用必须出现在 Submission 的 artifacts 列表中。
4. REQ 声称 pass 时，其必需产物必须有 present 绑定；失败/缺失提交仍可以合法记录。

独立复验结果：

| 用例 | 实际结果 |
| --- | --- |
| 原始无绑定的 Submission | 模型拒绝缺失 `artifact_bindings` |
| 全 pass，但 kernel/runner 显式 missing | bundle 拒绝 `passed requirement lacks a concrete required artifact binding` |
| kernel/runner 各有 present 引用，且引用列入 artifacts | 模型通过、bundle 返回空错误列表 |
| 原始 missing/unverified 草案 | 仍通过结构与关联检查，未被强行要求伪造成功产物 |
| 修复后六份 JSON Schema | 全部与当前模型生成结果一致 |

复验原件：`.tmp/contracts-v02-review/artifact-binding-recheck.json`；正例载荷：`.tmp/contracts-v02-review/recheck-positive-submission.json`。所验 `models_v02.py` SHA-256 为 `a4b4dbe2958e8120f95faeb1c3d1a05e6b3de89201bb0645c3d5010e136eca0b`。这些正例仍使用结构占位引用，只验证语义检查允许合法结构，不是实际执行、证据认证或接纳回执。

## 其他检查

- 独立变更 review 的 project、run、task revision、task digest、submission ID，均被 bundle 拦截；结果保存于 `audit-probes.json`。
- 读取并核对需求唯一性、must-have 未知引用、行为/连接覆盖、重复或遗漏 coverage、无证据 pass、人工判断待定与推荐 accept 的门禁；没有发现同级绕过。
- 模型明确要求双轴通过、列出的 coverage 全 pass、无 gaps 才能推荐 accept；bundle 再要求 coverage 精确枚举当前任务需求。单独 `ReviewDecisionV02` 合法不能替代 bundle 校验。
- Plan 可仅针对任务的部分需求；Submission/Review 仍须报告任务全部需求。这与模板一致，没有误把部分实验计划当成必须一次完成全部项目。
- Python 自定义 validator 不会全部编码进 JSON Schema，这一边界在 `V0.2.md` 已明确。六份 schema 无生成漂移。
- 人读模板将 JSON/ledger 作为权威，不从 Markdown 状态恢复运行；没有新增发布、改验收器或删除历史的隐含授权。产物绑定修复后已独立复核三份模板：SUMMARY 展示 `artifact_bindings` 四字段表及 present/missing 规则，VERIFICATION 要求复核绑定和提交原件归属，README 的追踪链纳入实际 `artifact_ref`。三者与修复后的模型语义一致，原同步提醒已关闭；本次仅复核文本，未重跑代码测试。

## 旧资产核查

旧 v0.1 的六份样本仍能由原模型解析，六份旧 schema 与原模型一致。`build_examples_v02.py` 只读旧 TaskSpec 样本，输出限定在 `examples/v0.2` 和 `schemas/v0.2`，未看到迁移或覆盖旧运行的路径。

对旧 `examples/gemv_loop/runs/final-reviewed-20261021/` 做只读复算：冻结 domain.py 与记录摘要一致，冻结 contract 一致，八轮 manifest 与所引用原件全部匹配；provider 仍是 `offline_deterministic`。证据：`.tmp/contracts-v02-review/legacy-read-check.json`。

这证明所检查旧样本仍可读、该正式 GEMV 记录当前完整；没有 Git 或本轮开始前全目录哈希基线，因此不扩大为“所有历史文件逐字节均未改变”的结论。
