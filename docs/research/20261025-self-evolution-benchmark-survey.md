# 自我进化与自动研究框架：实际测试案例调研

日期：2026-10-25。目的：为 ArcHa 与直接 Codex 的后续对照选择案例。本轮仅阅读原论文、官方项目页、仓库及任务注册表，未运行框架或新实验。本文件中的优先级是分析判断，不是本机可运行性证明。

后续用户明确偏好端侧架构、编译器/推理与性能/架构建模，并排除数学题、竞赛题作为主验证。下文外部框架调查保留；文末旧选题建议已由[Windows/CPU领域工程方案](20261025-domain-benchmark-proposal.md)替代，不能按旧优先级启动实验。

## 先明确研究对象

用户所称 Pi-SOL 对应 NVIDIA **SoL-Pi**。需区分两个优化层次：

1. **改任务解法**：FunSearch、AlphaEvolve、OpenEvolve、ShinkaEvolve 的算法优化任务，以及 autoresearch 的训练配置优化。ArcHa 当前与这一层最接近。
2. **改 agent/harness**：SoL-Pi、DGM、ADAS。搜索出的产物是 agent 的工具、控制流、上下文机制或代码，最终用独立任务集测其能力/效率。不能把“任务解法提高”直接称为“框架递归自我进化”。

详细证据分三份：[SoL-Pi](20261025-solpi-benchmark-evidence.md)、[算法进化](20261025-algorithm-evolution-evidence.md)、[DGM/RD-Agent](20261025-agent-rnd-evidence.md)。这些是同日协作调查笔记，结论以其中引用的一手来源为依据。

## SoL-Pi 实际使用什么

来源：[论文 v1，2026-09-17，§2–3](https://arxiv.org/html/2609.20519v1)、[NVIDIA 项目页](https://nvlabs.github.io/SoL-Pi/)、[官方仓库](https://github.com/NVlabs/SoL-Pi)。

| 用途 | 案例 | 核心评价 | 解释边界 |
| --- | --- | --- | --- |
| 发现 harness 改进 | 535 可执行环境：495 GitHub issue/PR 对 +40 verifier-driven 合成环境 | 能力约束下减少 token/费用；回归测试必须原先失败、参考补丁后通过 | PR 与隐藏回归测试不向执行 agent 暴露；不同于最终 benchmark |
| 长程最终评测 | EdgeBench 公开 51 题，其中11题单向接纳、40题最终泛化 | 任务得分、token traffic、API 估算费用 | 134 为全套数量，51 才是该公开评测口径；冻结候选后评价，反馈不回到搜索 |
| 终端任务迁移 | Terminal-Bench 4 中63个CPU任务 | 完成数、总模型费用、每成功任务费用 | 排除了GPU任务；不是整套所有任务 |
| 数学证明迁移 | IMO 2026 共6题 | Lean 4 形式化验证通过数、费用 | 每题150分钟上限；与源码优化任务不同 |
| 多agent优化 | Anthropic original performance takehome | 冻结模拟器周期、API估算费用 | 每配置一次2小时；单Codex、Codex+20 Pi、Codex+20 SoL-Pi，不是多次重复统计 |

内核试验结果：单agent1333 cycles/$39.20，20 Pi workers 1366/$82.12，20 SoL-Pi workers 1127/$60.11。证据支持这一组配置的质量与成本权衡；单agent仍最便宜。该题与 ArcHa 已有 kernel-opt 同源，不算新发现的独立案例。[原始结果](https://nvlabs.github.io/SoL-Pi/#swarm)

不能把“效率提升”改写为“能力全面提升”：论文 GPT-5.6 Sol 的四机制 Efficiency 配置相对 Pi，token traffic 约减49%，平均分44.8→42.0；Performance配置则是另一个运行点。Terminal-Bench完成数18→15。能力与费用必须同时报告。[论文表1–3](https://arxiv.org/html/2609.20519v1#S3)

EdgeBench 官网的全套任务分类包括 job-shop，但不能据此声称 SoL-Pi 公布了 job-shop 单题结果；应查具体公开51题注册表。

## 其他框架的案例地图

| 框架 | 实际案例 | 怎样衡量 | 对ArcHa的用途 |
| --- | --- | --- | --- |
| ShinkaEvolve | 26圆装箱；AIME推理agent；ALE-Bench启发式竞赛；MoE负载均衡损失 | 几何合法性与半径总和；正确率/LLM调用数；public/private竞赛得分；训练及下游指标 | ALE-Bench从已有强解继续优化，最能避免“恢复弱基线就完成” |
| FunSearch | cap-set构造；online bin packing | 结构合法性与集合大小；装箱数/相对下界 | 固定执行骨架，只进化启发式评分函数，CPU任务接入范围清晰 |
| AlphaEvolve | 数学构造、矩阵乘法算法、计算系统调度/内核等 | 自动数学验证或系统性能 | 可借评价原则；生产系统案例不等于有现成公开复现包 |
| OpenEvolve | 作者参与报告中的30个AlgoTune任务；另有圆装箱、排序等仓库examples | 输出正确条件下加速比，跨任务聚合 | AlgoTune比仅看仓库toy example更有依据；examples不等于同预算论文对照 |
| autoresearch | 单GPU小型语言模型训练，改train.py的架构/优化器/超参数 | 每次固定300秒训练，val_bpb越低越好 | 自然多轮且有可解释数据，但需要GPU；固定验证集不等于独立最终测试 |
| DGM | SWE-bench软件修复；Polyglot多语言编码 | 隐藏测试解决率，及进化轨迹/消融 | 用于研究agent自身修改；ArcHa若只改外部解法，研究对象不同 |
| ADAS | ARC网格变换；DROP阅读；MGSM数学；MMLU；GPQA；跨域迁移 | 正确率/F1，验证集搜索、测试集评价 | 适合agent控制流搜索；不必作为第一批源码性能测试 |
| RD-Agent | MLE-bench的Kaggle任务；RD-Agent-Q股票池因子/模型研发；RD2Bench因子实现 | 竞赛指标/奖牌；IC/RankIC与回测指标；实现正确性/不可实现需求识别 | 金融方向应参考跨股票池、跨年的独立测试，而非只优化单股六个月收益 |

一手入口：

- [ShinkaEvolve官方四领域说明](https://sakana.ai/shinka-evolve/)、[原论文](https://arxiv.org/abs/2509.19349)、[ALE-Bench](https://github.com/SakanaAI/ALE-Bench)。
- [FunSearch官方说明](https://deepmind.google/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/)、[官方代码](https://github.com/google-deepmind/funsearch)。
- [AlphaEvolve官方介绍](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)。
- [OpenEvolve作者参与的AlgoTune报告](https://huggingface.co/blog/driaforall/towards-open-evolutionary-agents)、[AlgoTune官方154任务仓库](https://github.com/oripress/AlgoTune)。
- [autoresearch README](https://github.com/karpathy/autoresearch)。
- [DGM官方说明](https://sakana.ai/dgm/)、[DGM论文](https://arxiv.org/abs/2505.22954)。
- [ADAS论文v1](https://arxiv.org/html/2408.08435v1)、[官方代码](https://github.com/ShengranHu/ADAS)。
- [RD-Agent官方仓库](https://github.com/microsoft/RD-Agent)、[MLE-bench原始基准](https://github.com/openai/mle-bench)。

## 特别值得借用的测试设计

### 从强解继续优化：ShinkaEvolve / ALE-Bench

ShinkaEvolve在ALE-Bench LITE的10题上从ALE-Agent已有解继续进化50代，而非从空白实现或极差初始解出发。搜索使用public得分，private测试用于最终评价。具体题目包括：

- **AHC039**：用有几何约束的轴对齐多边形捕获目标点，优化鲭鱼数减沙丁鱼数。[题面](https://atcoder.jp/contests/ahc039/tasks/ahc039_a)
- **AHC025**：在有限称重比较次数下把物品分组，尽量均衡总重量。[题面](https://atcoder.jp/contests/ahc025/tasks/ahc025_a)

这些具有连续改进空间、执行时限与可验证输出。它们仍可能被更强模型快速改进，不能在未做难度校准前保证需要多轮。[论文与官方结果](https://arxiv.org/abs/2509.19349)

### 输出等价条件下提速：OpenEvolve / AlgoTune

OpenEvolve作者参与报告实际用了30个AlgoTune任务，29个实验配置，常见100或200次迭代；例子包括count_connected_components、psd_cone_projection、DCT和SHA256。当前AlgoTune仓库全套154题，不等于该报告用了154题。报告没有建立与直接Codex的同模型同预算对照，不能用作者的加速数字预估ArcHa收益。[作者报告](https://huggingface.co/blog/driaforall/towards-open-evolutionary-agents)

挑任务时要检查目标是否已被库实现饱和、是否只要换一个库函数就解决，以及依赖是否允许。SHA256之类接近现成底层实现极限的题可以是负对照，不宜假定能持续提速。

### 长程真实工程：SoL-Pi / EdgeBench

公开注册表提供了直接可追踪的task ID。以下描述来自注册表，未启动镜像或审核完整judge实现，因此尚未确认本机运行条件、实际尺寸及全部评分权重。[官方任务注册表](https://huggingface.co/datasets/ByteDance-Seed/EdgeBench/blob/main/tasks.jsonl)

| task ID | 实际工作 | 目标与约束 | 初步适配判断 |
| --- | --- | --- | --- |
| ann_vector_search_qps | 将NumPy暴力最近邻替换为近似向量检索实现 | 满足召回硬约束后提高QPS | Python接口、质量/速度权衡，优先 |
| integer_compression_codec | 优化uint32整数编解码，涉及delta、bit-packing、SIMD | 无损往返必须正确，改善压缩率和解码吞吐 | 边界清楚、易设冻结测试，优先 |
| exchange_core_throughput | Java金融撮合引擎，线程拓扑/等待策略/环形缓冲/订单簿/JVM | 提高吞吐 | 真工程任务，但对机器负载敏感，接入较重 |
| borden_source_inversion | 从稀疏带噪监测井观测反推三维地下水污染源 | 自建forward model和反演优化 | 与用户“性能建模”的研究形态更接近，但领域准备较重 |
| jagua_nesting_optimization | 不规则二维排样 | 几何可行性及优化得分 | 有长程优化空间，先核查judge/依赖 |

EdgeBench官方按2/4/6/8/10/12小时报告曲线，独立work/judge环境隔离，并提供反复提交反馈。全量运行昂贵；ArcHa可借少量案例和评价协议，缩短预算的实验应称“所选任务上的自定义预算对照”，不能冒充官方榜单成绩。[官方仓库](https://github.com/ByteDance-Seed/EdgeBench)

## 金融方向的实际参考

RD-Agent-Q主实验采用CSI300股票池，2008–2014训练、2015–2016验证、2017–2020年8月测试；还有不同股票池/时期扩展。这里评价的是因子与模型在独立时间段及股票池的作用，而不是在已知单股短窗口上反复优化收益。RD2Bench的因子实现与不可实现需求识别则是另一种可确定评价的金融任务。[详细一手出处与版本边界](20261025-agent-rnd-evidence.md)

对“江西铜业近六个月”更合理的保留方式：把六个月定义为一次最终留出检验，开发使用此前数据；或者先做冻结因子定义的实现正确性与跨股票池效果。这里是实验设计建议，不是投资收益判断。

## 给ArcHa的选择建议（尚未批准实施）

第一批不继续扩张自造案例，优先复用三类已有基准：

1. **算法搜索**：ALE-Bench选AHC039/AHC025中的一项，从合法已有启发式或强解起步，验证“在已有成果上继续研究”。
2. **代码性能**：AlgoTune选2–3个不同结构任务，验证正确性约束下持续提速，并观察没有收益时能否合理停止。
3. **真实工程**：EdgeBench选integer_compression_codec或ann_vector_search_qps一项，验证跨文件调查、实现、反馈和成本。

若希望第一批包含数据驱动研究而非三项算法/工程，可把第3项替换为MLE-bench的小数据完整比赛，例如spooky-author-identification或nomad2018-predict-transparent-conductors，使用官方重新切分的留出评分。数据小不代表所需机器/训练时间已核实，仍需审任务包。[MLE-bench](https://github.com/openai/mle-bench)、[RD-Agent论文v2](https://arxiv.org/html/2505.14738v2)

只允许小样本时，从上面各挑一项比堆十个toy任务更能区分能力。openTPU作为领域案例后置：它仍有价值，但需自建/校准周期真值与划分，无法直接借现成统一分数。FT06保留为流程smoke。

比较指标：独立正确性/可行性；原始目标；最好有效目标值随墙钟和累计token变化；达到同一质量所需成本；无效候选/人工修复。保留开发与最终留出隔离。流程成本分首次map/task/onboard总成本与执行期；直接Codex也允许自主多次修改测试。不要只用轮数、成功案例终值或候选自报耗时证明优势。

下一步应先审阅上述候选的任务包、judge、资源要求和预算方案，形成可审阅实验卡；本调研不授权启动试跑。

## 版本与可复现性说明

此处版本锚点包括SoL-Pi arXiv:2609.20519v1、ShinkaEvolve 2509.19349v1、DGM 2505.22954v3、RD-Agent 2505.14738v2、RD-Agent-Q 2505.15155v2、ADAS 2408.08435v1。官网和GitHub main/master是访问日内容，尚未统一锁定commit；论文参数、当前examples与当前benchmark发布版本必须分别记录，不能当作同一个冻结实验包。
