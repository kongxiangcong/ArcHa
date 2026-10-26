# SoL-Pi 测试案例与评价证据

访问日期：2026-10-25。作者：research sub-agent。只读研究，未运行模型、benchmark 或修改实现。核对论文 HTML、官方项目页、仓库 README/目录和下游 benchmark 任务表；未完整审计算法代码。论文固定版本为 arXiv:2609.20519v1（2026-09-17）；GitHub 使用访问日 main，未取得完整提交 SHA，因此不把当前 main 当论文冻结版本。

## 对象与结论

用户所称 Pi-SOL 对应 **NVlabs/SoL-Pi**。它是建立在 Pi 上的独立扩展，主要目标是保持任务能力的同时降低 harness token/费用；开发它的 auto-research 流程和发布的四项效率机制需要区分。开源入口：[官方仓库](https://github.com/NVlabs/SoL-Pi)、[官方项目页](https://nvlabs.github.io/SoL-Pi/)、[论文 v1](https://arxiv.org/html/2609.20519v1)。

## 论文实际用哪些环境

| 用途 | 案例与数量 | 门与边界 |
| --- | --- | --- |
| 搜索开发 | 535 环境：495 个 GitHub issue–PR 对，另40个可执行 verifier 合成任务 | 仓库回退到修复前，隐藏 PR/回归测试，要求 fail-before/pass-after；合成任务主要用 Terminal-Bench-2-style 接口 |
| 泛化评价 | EdgeBench 公开51项 | 冻结候选后11项单向接纳、40项最终泛化；评价反馈不得回到搜索 |
| 终端任务 | Terminal-Bench **4** 的63个 CPU任务 | 排除需GPU任务；报告解题数、API总成本及每解题成本 |
| 数学证明 | IMO2026 六题 | Lean4验证；每题150分钟；GPT-5.6 Sol/xhigh |
| 优化搜索 | Anthropic original performance take-home | 每配置一次2小时；冻结起点147734 cycles，独立验收候选 |

上述是论文 §2.3、§2.5、§3.2–3.3 的实验对象，不能把开发集的 Terminal-Bench-2-style 接口写成最终测 Terminal-Bench2。[论文](https://arxiv.org/html/2609.20519v1)

## 对照、成本与重复的实际口径

官方项目页明确，EdgeBench 对照各模型使用 xhigh，比较 native harness、Pi、SoL-Pi；其问题强调数小时连续执行中累积的上下文和工具开销。不要从 EdgeBench 本身的12小时设置反推 SoL-Pi 每一条实验都运行12小时，当前查到材料没有统一给出全部行的精确时限与重复数。[官方项目页 Results/Discussion](https://nvlabs.github.io/SoL-Pi/)

kernel 搜索比较：单 Codex、Codex 协调器+20 Pi workers、同协调器+20 SoL-Pi workers；协调器/单agent为 GPT-5.6 Sol，workers为 GPT-5.6 Luna，全为 xhigh。三配置各一次2小时，不是同配置三重复；两条 control 顺序执行。结果分别为1333/$39.20、1366/$82.12、1127/$60.11 cycles/API-equivalent模型费用。单agent仍最便宜。8个速度阈值由独立正确性检查约束。[官方项目页 Swarm](https://nvlabs.github.io/SoL-Pi/)

论文把 token 分成 input、cache-read、cache-write、output，费用使用2026-08-17固定API价格；指标含平均任务分、总成本、成本/aggregate score。Efficiency完整栈保留约94%的Pi平均分，不能概括成完全无能力下降。搜索总成本及广度/深度等预算对照仍有限制。[论文 §3.1/§5.1](https://arxiv.org/html/2609.20519v1)

## 能具体复用的 EdgeBench cases

EdgeBench 官方公开51项，完整134项覆盖科学、系统工程、组合优化、知识工作、形式数学、游戏。完整集官网举例含job-shop，但公开51项表中没有job-shop，不能据此说SoL-Pi公开评价就跑了该调度题。[官网 taxonomy](https://edge-bench.org/)、[官方公开任务表](https://github.com/ByteDance-Seed/EdgeBench#leaderboard)

以下是已在公开任务表核实的准确 ID；中文说明是从名称和类别作的简述，尚未逐题审计 verifier：

| 准确任务ID | 内容简述 | ArcHa 候选价值（判断） |
| --- | --- | --- |
| ann_vector_search_qps | ANN向量检索吞吐 | 可同时设召回正确性门和吞吐目标；先查硬件与数据条件 |
| exchange_core_throughput | 撮合引擎吞吐 | 真代码性能优化；适合质量/资源曲线 |
| integer_compression_codec | 整数压缩codec | 正确性、压缩率和速度多目标，CPU可选方向 |
| jagua_nesting_optimization | 不规则排样 | 组合搜索，可能保留较长优化空间 |
| smt_solver | SMT求解 | 离散正确性加求解性能；依赖较重 |
| vehicle_routing_time_windows | 带时间窗车辆路径 | 合法性门明确，适合多实例/留出测试 |
| warehouse_forklift_routing | 仓储叉车路径 | 约束搜索；公开成绩说明存在持续难度 |
| borden_source_inversion | 地下水污染源反演 | 和性能模型一样属于有数值误差反馈的建模任务 |
| vliw_kernel_optimization | VLIW内核优化 | 与ArcHa现有takehome同类，先排查是否重复 |

[任务名及公开成绩一手来源](https://raw.githubusercontent.com/ByteDance-Seed/EdgeBench/main/README.md)。公开成绩是其他模型在该benchmark的结果，不是ArcHa已验证适配结果。

## 后续 Visual 扩展示例，不能混作原论文主评测

仓库2026-10-13发布Visual示例，要求从参考视频/图片重建Blender场景并渲染复核。它用VSI-Bench中的15场景，ARKitScenes/ScanNet++/ScanNet各5；GPT-6 Astra/high，对比Codex、SoL-Pi、SoL-Pi Visual；报告模型评审视觉分、记录费用、calls。它具有可重复修订的反馈，但视觉评分需要单独审查，不能视为与deterministic correctness相同。[官方Visual README](https://github.com/NVlabs/SoL-Pi/blob/main/examples/solpi-visual/README.md)

## 可复现边界与 ArcHa 借鉴

SoL-Pi仓库公开的是Pi扩展、配置与测试；本次核查的docs/scripts目录没有找到535环境的完整manifest/镜像/原始试验账本，不能宣称完整搜索已经可一键复现。EdgeBench则公开SForge评价框架和任务数据入口，README提供Docker/E2B等运行路径；要挑题仍需逐题查镜像、依赖、verifier与资源需求。[SoL-Pi scripts目录](https://github.com/NVlabs/SoL-Pi/tree/main/scripts)、[EdgeBench仓库](https://github.com/ByteDance-Seed/EdgeBench)

对ArcHa的判断：优先从公开的ANN吞吐、压缩codec、排样、车辆路径中挑2–3题，而不是继续人为制作一轮可解的小题。先核对连续分数、有约束的正确性、足够优化空间和留出接口，再形成方案；此记录不授权启动实验。SoL-Pi的核心可借鉴点是开发反馈与最终验收隔离、能力先过门再计效率、同时记录质量和累计成本。其20-worker swarm与ArcHa单控制器并非同一实验变量，不宜直接照搬比较。
