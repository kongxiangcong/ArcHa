# 探针断点调试

Labels: wayfinder:map

## Destination

确定用于检查自动推进框架的最小断点调试方案，便于逐步检查专家的假设与设计，并定位不合理方案的原因。只确定方案，不在本地图内实施。

## Notes

- 使用 wayfinder、grilling、domain-modeling；沿用[本地事项约定](../../docs/agents/issue-tracker.md)。
- 用户明确要求保持轻量：这是自动流程的调试选项，不是独立审阅或审批产品。
- 沿用[专题工作区决策](../../docs/adr/0001-topic-workspace.md)及现有执行、锁、材料和错误处理。

## Decisions so far

- [固定断点调试的最小范围](issues/01-review-control.md)：专家生成探针后停下，支持继续或方向反馈重拟；CLI 与现有工作台共用控制，保留排查所需原始材料。

- [CLI 与工作台断点/继续已交付](issues/02-breakpoint-continue.md)：专题持久化调试选项，共用引擎断点，真实浏览器与 Worker 验证只读检查和继续至下一探针。

## Not yet specified

无必须继续拆票的产品决策。参数命名、接口路径和最少的数据保存方式由实现时结合现有代码决定。

## Out of scope

- 独立审批状态机、审批历史、提案版本管理、完整聊天系统、第二份认知或假设账本。
- 任意位置断点、并发审阅流程、工作台整体重建。
- 通过局部反馈改变专题目标。

原先独立的反馈与界面事项已合并到最小范围，不再作为多轮产品设计推进。
