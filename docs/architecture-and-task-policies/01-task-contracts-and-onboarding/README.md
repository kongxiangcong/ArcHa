# S1 任务契约、Profile 与准备流程

状态：方向已建立，需求待讨论；本阶段可以在讨论后形成多份 spec 与多张 tickets。

入口：[总规划](../ArcHa_Phased_Development_Plan.md)。整体文档依据：[§4](../ArcHa_Overall_Architecture_and_Task_Policies.md#s04)、[§5](../ArcHa_Overall_Architecture_and_Task_Policies.md#s05)、[§6](../ArcHa_Overall_Architecture_and_Task_Policies.md#s06)、[§7](../ArcHa_Overall_Architecture_and_Task_Policies.md#s07)、[§13](../ArcHa_Overall_Architecture_and_Task_Policies.md#s13)。

**依赖：** S0。目标是把用途、交付和边界可靠地传入执行端。

## 需要讨论的方向

- 明确四个入口的输入输出、责任、失败/未就绪状态，以及明确工程任务直接进入 Task 的路径。研究地图只保存方向和依赖，不把“简报已写好”误当“依赖成果已完成”。
- 确定 Brief、任务配置、Profile 默认值、本机绑定和生效快照的关系；讨论实际配置格式、版本、覆盖优先级、硬限制、缺失值和合同修订。Profile 提供默认策略，Activity 不变成权限或固定步骤。
- 明确 Onboard 的准备边界：验证/观测通道可用与最终功能完成分开；冻结验收含义与必要参照，动态实验设计留给 Worker。
- 让观察端能追到“该值从哪里来、哪个 revision 生效、为何 ready/blocked”。复用已有状态和投影，先支持最小实际流程。

## 拟议结束条件

一个开发或优化任务从简报进入可执行契约并沿现有引擎运行；三类任务的配置意图可表达，未实现能力明确保持未就绪，不因配置解析成功宣称可执行。冲突和实质修订有清楚行为。

**留到阶段讨论：** JSON/YAML、默认值数量、旧配置支持范围与迁移方式。本阶段不建设任意 Profile 插件系统。

## 优先收敛的问题

1. 四个入口各自接受什么、保证什么，哪一步负责消除意图与可执行契约的冲突？
2. 哪些值是任务默认、环境绑定或不可放宽的硬边界；怎样避免多份配置各自成为权威？
3. 面向最终 DeepStack 任务，准备状态需要证明哪些通道可用，而不提前要求研究答案？

本阶段使用必要的框架回归、夹具或轻量案例获得反馈；DeepStack 正式建模探索留到 S6。方法变化回写总规划中的测试方法约定，不在此提前运行研究。

下一方向：[S2](../02-attempts-and-worker-handoffs/README.md)。
