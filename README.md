# Ge / OPC 自动研发框架

本目录包含通用OPC设计、项目接入协议、接口合同草案和已运行的离线验证。更新：2026-10-22。

从[OPC 框架实现方案](OPC%20框架实现方案.md)开始阅读。核心分工是 Winson 独立咨询、Ge 统一入口、确定性控制层管理专家—设计—独立验证循环。

| 入口 | 内容 |
| --- | --- |
| [原始交接](OPC%20自主研发工作流交接.md) | 输入背景，保留原文 |
| [实现方案](OPC%20框架实现方案.md) | 选型、架构、状态机、预算、恢复、分阶段验收 |
| [项目接入与目录规范](OPC%20项目接入与目录规范.md) | 任意项目如何接入；实验、源码工作区、冻结提交与审核放在哪里 |
| [合同v0.2](contracts/V0.2.md) | GSD参考后的需求追踪、项目/组件/基线、行为与连接检查 |
| [接口合同](contracts/README.md) | Pydantic、JSON Schema、MRD/SPEC、轮次与审核模板 |
| [接入工具与两项目示例](examples/project-onboarding/README.md) | 只写新.opc的初始化、路径规划和源码不变证据 |
| [本轮接入验证](docs/integration-validation.md) | 新合同反例、路径测试、独立复核及尚未实现项 |
| [GEMV 示例](examples/gemv_loop/README.md) | 安装/运行/恢复命令、模型、局限 |
| [验证报告](docs/validation.md) | 实际结果、失败路径、独立审核与尚未验证项 |
| [底座核查](docs/research/runtime-reuse.md) / [优化器核查](docs/research/optimization-reuse.md) | 官方与固定版本源码证据 |
| [讨论白板](docs/discussions/opc/winson-whiteboard.md) | 当前决定与返回点 |

当前原型没有模型调用：用规则专家、模板代码生成器和独立 Python 验证进程，实际复用 LangGraph 与 SQLite。它验证控制层可行性，不代表 Ge 服务、真实 LLM 自主研发或硬件 PPA 已通过验收。
