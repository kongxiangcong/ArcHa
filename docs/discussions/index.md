# 讨论索引

| 分组 | 专题 | 范围 | 状态 | 白板 |
| --- | --- | --- | --- | --- |
| 整体与历史 | OPC / ArcHa 历史讨论 | 架构、工作流与实现的历史混合记录，沿原路径保留 | 持续 | [原白板](opc/winson-whiteboard.md) |
| 整体架构与任务策略 | 开发流程与阶段规划 | 大方向分阶段改造；测试方法前置，改造完成后验证 DeepStack 建模探索 | S0 已收束；S1 七票已实现并验证，正式考试未运行 | [阶段规划](../architecture-and-task-policies/ArcHa_Phased_Development_Plan.md) |
| 整体架构与任务策略 | S3 证据与共享知识 | 原始观测、主张修订与后续上下文 | 需求及测试边界已确认，规格已发布；未实施 | [专题入口](../architecture-and-task-policies/03-evidence-and-shared-knowledge/README.md) |
| 整体架构与任务策略 | S4 任务策略、成果接纳与交付闭环 | 三类任务的进展与完成、版本选择、独立审核及终验失败处理 | 规格及六票已发布为 ready-for-agent；拆分与测试范围已确认，未实施 | [专题白板](../architecture-and-task-policies/04-task-policies-and-delivery/README.md) |
| 整体架构与任务策略 | S5 沉浸式调试工作台 | 观察/API、Engine 控制与沉浸式体验；诊断返回及暂停/继续 | 原型/布局、测试边界与拆分已确认；spec 及六票已发布为 ready-for-agent，未实施 | [专题白板](../architecture-and-task-policies/05-debugging-workbench/README.md) |
| 评测 | S0 共同边界与四题测试方法 | 执行粒度、Worker/DAG、轻量记录；开发、调优、探索与独立端到端考题 | 需求已收束；四题材料及环境准备，正式考试未运行 | [专题白板](evaluation/s0-modeling-exploration/winson-whiteboard.md) |
| 评测 | 自我进化框架的测试案例 | 真实工程/探索五候选、ArcHa与自主Codex对照、两项实验卡 | 实验卡待审；只读WSL检查完成，未安装或实验 | [专题白板](evaluation/benchmark-cases/winson-whiteboard.md) |

S1 交付入口：[任务契约与准备流程](../architecture-and-task-policies/01-task-contracts-and-onboarding/README.md)；沿规格查看实现、最终验证与原始证据。[S2 Attempt 与 Worker 交接](../architecture-and-task-policies/02-attempts-and-worker-handoffs/README.md)的核心流程、最小交接、重试及暂停/停止规则已确认；代码与 CLI 能力只读核查完成，grill-with-docs 需求澄清已收敛，[实现规格](../../.scratch/s2-attempts-and-worker-handoffs/spec.md)及 [7 张事项](../../.scratch/s2-attempts-and-worker-handoffs/issues/)已发布为 ready-for-agent；DSH 当前仅实现的验证例外见规格，尚未实现。
