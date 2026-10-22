# 专家 → 设计 → 验证：一轮交接模板

## 专家 ExperimentPlan

- 绑定 TaskSpec revision/hash、父提交、已接纳结论与失败记录。
- 单一可证伪假设；为什么现在测它。
- 竞争解释；怎样用本次实验区分。
- 只改什么、控制什么、评价器/工作负载版本。
- 预计预算上界、命令 argv、产物清单、失败后的分支。

## 设计 Submission

- plan/attempt/call ID，代码快照、输入、环境、命令与原始 stdout/stderr/exit code。
- manifest/hash，功能结果、指标和单位。
- 主张、每条对应证据、成立条件、反例、失败项、未知项。
- 不自行签署审核通过；变动生成新 Submission。

## 独立验证 ReviewDecision

- 服务分配的 reviewer call 身份；绑定合同与不可变 manifest。
- Standards：可改范围、工程质量、可复现性、测试/评价器是否被改、证据完整性。
- Spec：需求覆盖、独立正确性、工作负载一致性、指标口径、对照是否公平、主张是否超出证据。
- 两轴分别 pass/revise/fail/inconclusive；不能平均成总分掩盖一个轴失败。
- 复算原件与命令，实验结论、条件、未知项、补证要求。
- 推荐 accept/revise/reject/blocked；最终接纳由确定性服务决定。

## 专家下一轮

- 保留哪些已审核结论，否定哪些假设。
- 同一路线修补、换假设、停止或请求用户决定的理由。
- 接纳的改进候选才成为新 parent；被拒绝实验仍进入负面证据档案。
