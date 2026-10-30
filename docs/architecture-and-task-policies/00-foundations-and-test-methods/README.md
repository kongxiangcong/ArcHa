# S0 共同边界与测试方法

状态：方向已建立，需求待讨论。此处是大的设计与准备方向。

入口：[总规划](../ArcHa_Phased_Development_Plan.md)。依据：[整体文档 §1](../ArcHa_Overall_Architecture_and_Task_Policies.md#s01)、[§5](../ArcHa_Overall_Architecture_and_Task_Policies.md#s05)、[§8](../ArcHa_Overall_Architecture_and_Task_Policies.md#s08)、[§15–18（起点）](../ArcHa_Overall_Architecture_and_Task_Policies.md#s15)。

## 目标与边界

明确共同语义、工程约束、现状复用与迁移边界，并把最终 DeepStack 建模探索的测试方法前置到开发讨论。先确定什么需要观察和怎样核对，具体研究答案与实验路线留给改造后的 ArcHa。

本阶段不依赖其他阶段；其结论约束 S1–S5，并向 [S6](../06-deepstack-exploration-validation/README.md) 传递测试目标和证据标准。

## 需要讨论的方向

- 共同对象：Task、Contract revision、Run、Attempt、Call、Experiment、Measurement、Claim、Artifact 的区别、身份和关联。只先明确跨模块所需语义，不一次规定全量字段。
- 工程约束：将总规划中的轻量、模块化、渐进披露、数据与结论管理要求变成 review 时可判断的规则；列出现有能力应保留、调整和补齐的部分。
- 迁移边界：旧合同、账本、原件、观察 API、项目内 runtime 与技能副本怎样继续读取或显式升级；在修改协议前说明哪些旧运行支持续接。
- 调试用途：从“谁在做什么、停在哪里、收到哪些材料、结论为何变化”等问题定义观察出口，讨论只读观察与运行控制/知识编辑的首版边界。
- 前期反馈：选择已有回归或小型合成案例验证框架行为，设计必要成本和观察开销的记录方式；不启动 DeepStack 探索。
- 最终测试方法：按[总规划 §4](../ArcHa_Phased_Development_Plan.md#deepstack-test-method)讨论 DeepStack 研究范围、可见材料、交付证据、独立核对方式与完成标准。

## 优先收敛的问题

1. 希望理解 DeepStack 的哪条建模链路、哪些层级，以及这些认识将用于什么建模或架构决策？
2. 研究执行者可以读取哪些源码、文档和运行信息；哪些关键主张需要行为验证，哪些可由明确实现事实支撑？
3. 什么产物足以说明“摸清楚约定范围的建模方法”，哪些未知可保留，哪些缺口会使交付未完成？
4. 运行、交接、知识与观察之间最少需要哪些共同身份和状态，才足够外层调试工具定位问题？

这些问题是阶段讨论入口，不要求本次创建目录时回答。

## 预期产出与结束条件

形成已确认的共同边界、现状/迁移判断和测试方法要求，能说明每项必要能力怎样被观察和验证。DeepStack 的最终测试范围与方法有清楚依据；不要求现在知道其建模答案，也不把环境登记当成已运行。

之后进入 [S1 任务契约与准备流程](../01-task-contracts-and-onboarding/README.md)。本阶段不建设新引擎、完整协议全集、全部 benchmark 或新 UI；没有实现缺口时不制造代码工单。
