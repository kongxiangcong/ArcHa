# 文档导航

当前引擎行为以 [opc/README](../opc/README.md) 和 [接入指南](../opc/scaffold/ONBOARDING.md) 为准。设计基线、历史报告保留当时的版本和结论边界；不能用历史验证证明当前版本已经实测。

| 目录 / 文件 | 存放内容 |
| --- | --- |
| [design/](design/) | 框架设计、接入与目录规范；原根目录两份设计文档迁入这里 |
| [research/](research/) | 固定版本论文、源码与复用方案核查 |
| [discussions/](discussions/) | 用户确认的方案、纠偏与后续讨论入口 |
| [下一阶段方向](plans/archa-next-stage-goals.md) | 先建测试平台与真实案例，再逐项验证阅读接口、研究闭环、共享经验与只读 dashboard；待验证路线，不是全面实施规格 |
| [reviews/](reviews/) | 独立审核和复核记录；原 docs/review-*.md 迁入这里 |
| [reports/](reports/) | 可提交的验证摘要、条件、结果与证据路径 |
| [evidence/](evidence/) | 已保留的审核探针与原始证据 |
| [cross-platform.md](cross-platform.md) | Windows / Linux 使用与环境边界 |
| [validation.md](validation.md)、[integration-validation.md](integration-validation.md) | v0.1 / v0.2 历史验证索引 |

设计入口：[框架实现方案](design/OPC%20框架实现方案.md)、[项目接入与目录规范](design/OPC%20项目接入与目录规范.md)。近期实现依据见 [OPC 讨论白板](discussions/opc/winson-whiteboard.md)，历史 Windows FT06 与 onboard 记录见 [reports/README](reports/README.md)。

当前改造：[任务完成主线 spec](design/task-completion/spec.md) 与 [实施 tickets](design/task-completion/tickets.md)、[工程验证方案](design/task-completion/validation.md) 与 [开发提示词](design/task-completion/development-prompt.md)（2026-10-27；逐票实施及真实验证状态以 tickets 为准）。

任务成果统一：[实施 tickets 与字段归属](design/task-results/tickets.md)、[使用与升级](design/task-results/usage.md)。支持跨 run 实验关联、当前累计成果消费、审核版本和只读成果入口；验证状态以 tickets 为准。

测试项目统一放在 [benchmarks/](../benchmarks/README.md)：DMA 背压用于闭环冒烟，DeepStack 主线固定版本已登记、任务待定。各项目的 reports 保存可提交摘要，runs 保存不提交的独立工程、账本、工作树和完整日志。旧 benchmark 工具及 FP32 包已退役，历史准备记录迁至 [reports/benchmark-preparation-20261024/](reports/benchmark-preparation-20261024/preparation-20261024.md)。已有未跟踪运行原件和缓存不随本次整理删除。

新报告注明日期、代码/合同版本、验证范围与证据来源。报告中的旧根目录文件名、绝对路径和当时的未提交状态属于历史事实；目录调整只修正文档链接，不改写历史结果。
