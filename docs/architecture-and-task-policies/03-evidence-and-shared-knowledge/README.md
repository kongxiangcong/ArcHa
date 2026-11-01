# S3 证据、主张与共享知识

状态：需求讨论及测试边界已确认（2026-10-31），[规格](../../../.scratch/s3-evidence-and-shared-knowledge/spec.md)及 [7 个实现事项](../../../.scratch/s3-evidence-and-shared-knowledge/issues/)已发布，状态为 `ready-for-agent`。当前可从事项 01 开始，后续按各事项的阻塞依赖推进；未实施或执行本阶段验收。

本页保留阶段导航和设计取舍；实现与验收要求以规格为唯一权威来源，术语以根 [GLOSSARY.md](../../../GLOSSARY.md) 为准。

## 阅读入口

- 实现前阅读：[S3 规格](../../../.scratch/s3-evidence-and-shared-knowledge/spec.md#implementation-decisions)。
- 验收与测试边界：[Testing Decisions](../../../.scratch/s3-evidence-and-shared-knowledge/spec.md#testing-decisions)。
- 范围与减法：[Out of Scope](../../../.scratch/s3-evidence-and-shared-knowledge/spec.md#out-of-scope)。
- 阶段安排：[总规划](../ArcHa_Phased_Development_Plan.md)；后续方向：[S4](../04-task-policies-and-delivery/README.md)。

## 接续依据

S3 依赖 S2，目标是让后续工作利用真实经验并修正旧判断。共同语义与披露原则沿用 [S0 定稿](../00-foundations-and-test-methods/README.md)；契约、结果反馈、恢复与工具边界以 [S1 交付记录](../../../.scratch/s1-task-contracts-and-onboarding/spec.md#交付验证)及 [S2 交付记录](../../../.scratch/s2-attempts-and-worker-handoffs/spec.md#交付验证)为准。本轮仅核查代码及测试结构，没有重新运行这些验证。

整体架构背景见 [§4](../ArcHa_Overall_Architecture_and_Task_Policies.md#s04)、[§9](../ArcHa_Overall_Architecture_and_Task_Policies.md#s09)、[§10](../ArcHa_Overall_Architecture_and_Task_Policies.md#s10)、[§11](../ArcHa_Overall_Architecture_and_Task_Policies.md#s11)及 [§14](../ArcHa_Overall_Architecture_and_Task_Policies.md#s14)。整体文档中的早期方案仅保留背景，S3 的收敛要求以规格为准。

## 讨论依据与取舍

**保存结果不等于修正认识。** 讨论以虚构 CSV 测量案例区分长字段提速、短字段退化及资源争用干扰；该案例没有实测。只追加最新摘要成本较低，但无法保证旧主张被修正、两次观测可比或反证进入后续选择，因此将实际交接与下一步选择纳入验收，案例细节统一见规格。

**主张身份不能随范围漂移。** 把“全部输入提速”直接改成“长字段提速”，会悄悄改变历史引用的含义；反馈分析与持续主张也不能压成每次 Attempt 一条记录。本轮据此澄清术语和身份边界，具体规则已纳入规格。

**复用底座，补齐消费路径。** 已有成果登记、原件引用、SQLite 账本及单写入机制，无需再建文件系统或知识服务；但带预算的顺序展开并不等于按问题查询。纯 Markdown/JSON 承载所有结构化状态会重复实现已有查询与写入协调，因此沿既有持久记录扩展。

**采用由判断者声明，冲突以整份决策处理。** 材料传入或读取不证明它成为决策依据；部分提交又需要额外表达反馈、修订与工作选择之间的生效关系。首版接受同份回复中无冲突部分也需等待的代价，换取一致的登记与恢复边界。

**外部材料管理已撤回。** 早前提出的外部资料归档、版本或读取时间登记方案均不构成需求；这项减法不改变 ArcHa 自产必要证据的保存约定。具体排除范围统一见规格。

前轮参考了 [W3C PROV-DM](https://www.w3.org/TR/2013/REC-prov-dm-20130430/) 的来源关联思路及 [MLflow Architecture Overview](https://mlflow.org/docs/latest/self-hosting/architecture/overview/) 的元数据与原件存储职责分离。这些仅是讨论参照，不构成引入 RDF、完整 PROV 或 MLflow 的理由；本轮规格发布未重新核查外部资料。
