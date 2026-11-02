# S0 四题准备与环境自检（2026-10-31）

状态：**S0 需求已收束，四题材料及本地运行环境已准备并通过自检。** Ramulator 同版本计时校准完成。此报告记录准备事实，不是正式 ArcHa 考试或优化结果。

入口：[S0 决定](../../architecture-and-task-policies/00-foundations-and-test-methods/README.md)、[四题](../../../benchmarks/README.md)、[运行与外置核对](../../../benchmarks/ENVIRONMENT.md)。

| 自检 | 结果 |
| --- | --- |
| 开发题判题器 | 参考实现通过111用例和4个公开用例；错误实现被99个用例拒绝；题内仍为未实现入口 |
| 探索题依赖/接口 | 官方 test_custom_arch_profile.py，51项通过 |
| 端到端环境 | 官方 custom_accelerator.py 成功运行 |
| 本地工具隔离 | 7项检查通过：外部库/兄弟题/验收器不可读，题外不可写，socket禁止，题内可写，子进程继承 |
| Ramulator | 两个 Release 构建成功，12组事件/统计完全一致，观察探针未改变统计；正式规模同版本计时比0.9989 |

固定材料及独立初始提交见 [materials.json](materials.json)，工具链/依赖提交见 [environment.json](environment.json)，隔离结果见 [isolation.json](isolation.json)。逐文件哈希和大型原件留在各题 runs/prepared；原始许可随源码保留，不复制未提交上游改动。论文下载件由 SHA-256 固定，不假定浮动 PDF URL 是不可变版本。

开发判题器重放：`python3 benchmarks/deepstack-development/examiner/selfcheck.py --output <新的操作者目录>`。完整输出在 `benchmarks/deepstack-development/runs/final-judge-selfcheck`。开发语义是从上游提炼的公开单层接口，参考判题不是对 DeepStack 全部拓扑/层级的准确性证明。

DeepStack 官方示例输出19.838 ms、3226.055 tokens/s，只用于确认该固定环境可执行，不作为模型准确性或题目答案。其 stdout/stderr 位于端到端题 runs/prepared/smoke.*。探索自检命令、构建入口和隔离启动方式均见环境说明。

本次不执行 Map/Task/Loop 正式研究、不提供题目解法、不实现 ArcHa DAG/会话/控制台改造。正式 Worker 全工具隔离接入仍须 S2 验证；本次隔离结果只覆盖启动器执行的本地进程。正式考试在 S1–S5 必要工作及集成验收后开展。

Ramulator [自检数据](ramulator-selfcheck.json)覆盖264,012次接收拒绝、46条刷新命令、6,896次完成和25,099次选择事件；12组均满足轨迹一致、统计一致及探针不改变统计。比较的是原版与原版，不是优化实现。小规模计时速度比几何均值1.008，不满足提速门槛，符合预期。原件位于调优题 examiner/private/selfcheck-20261031，基线原件在 examiner/private/baseline-*。开发判题器数据见 [development-selfcheck.json](development-selfcheck.json)。

## 正式规模计时校准

[原始成对数据](ramulator-calibration.json)：三类各100,000请求，五对交替测量，固定同一CPU核，无编译工作并发。两侧都是未优化原版。

| 负载 | 基线墙钟中位数 | 中位速度比 | 单对速度比范围 |
| --- | --- | --- | --- |
| stream | 1.882 s | 1.0056 | 0.9714–1.0468 |
| random | 1.315 s | 0.9930 | 0.9064–1.0285 |
| samebank | 11.119 s | 0.9981 | 0.9347–1.0338 |

综合中位速度比几何均值 **0.9989**，未触发5%提速门槛。各进程峰值RSS记录于原始数据。单对波动可接近10%，所以不能拿单轮胜负声称收益；5%是公开的实用收益门槛，不是统计置信界限。正式验收使用五对、各族中位数及至少四对综合胜出，接近噪声时排除干扰后完整复测，不挑有利轮次。此结果证明本机固定输入存在可测运行成本，仍不证明一定有可达优化。

校准可重放：`python3 benchmarks/ramulator2-optimization/examiner/calibrate.py --output <新文件>`；要求准备工程仍为原版，且其他构建/测量已经停止。冻结基线的源码和二进制摘要在 `benchmarks/ramulator2-optimization/examiner/private/baselines.json`。

准备工具语法检查、文档链接检查及 `git diff --check` 通过。未运行全套 ArcHa 框架回归，因为本轮未修改框架实现；正式集成仍由 S1–S5 负责。
