# 自动算法进化框架的实际测试案例：一手证据

日期：2026-10-25。调查者：research sub-agent。范围：AlphaEvolve、ShinkaEvolve、FunSearch、OpenEvolve、karpathy/autoresearch。只阅读官方论文、仓库、作者文章与评价代码，未运行任何实验、未安装框架。论文版本明确列出；GitHub `main/master` 为本日访问内容，未锁定 commit，不能作为未来可复现版本。

## 结论与 ArcHa 的关系

这些系统主要进化任务程序、启发式或训练配方，而不是更新基础模型权重。对 ArcHa 最直接的迁移对象是 **ALE-Bench 的强初始解继续优化**、**FunSearch 的在线装箱优先级函数**、**AlgoTune 的数值程序提速**。它们分别覆盖复杂算法优化、固定接口的启发式设计、正确性约束下的性能工程。研究方案应先选任务与独立评价器；无需先复制别人的整个进化框架。

本判断是对已读任务定义的推断，不是 ArcHa 实测结论。公开已知最优解和发现程序可被模型记忆，必须记录污染风险；能否避免一轮达标需要难度校准，不能仅由任务名称保证。

## 1. ShinkaEvolve：最直接的多轮优化参考

主要来源：[论文 arXiv:2509.19349v1，2025-09-17](https://arxiv.org/html/2509.19349v1)、[Sakana 官方介绍，2025-09-25](https://sakana.ai/shinka-evolve/)、[官方仓库](https://github.com/SakanaAI/ShinkaEvolve)。论文与当前仓库 API 已有版本差异，不将当前示例默认值视为论文参数。

| 论文实际案例 | 进化对象、目标与预算 | 最终评价 |
| --- | --- | --- |
| Circle Packing，26 个圆置于单位正方形 | 进化求解程序，最大化半径之和；150 代 | 边界与不重叠约束；搜索验证容许 `1e-6` slack，另用 AlphaEvolve 精确约束复验 |
| AIME | 在 AIME 2024 的30题上进化 agent scaffold；75代，单题最多10次LLM调用；每候选完整题集独立评3次 | AIME 2023/2025及不同底层LLM检验泛化 |
| ALE-Bench LITE | 10道AtCoder启发式题；从ALE-Agent已有强解出发，每题50代，以public集评分搜索 | private集评价；论文报告平均约2.3%改进 |
| MoE负载均衡损失 | 556M参数、64专家/激活8专家、超过2B fineweb tokens；30轮，目标结合交叉熵和负载不均衡 | 扩至2.7B、近30B tokens复验；GPU训练成本明显高于CPU算法题 |

具体 ALE 题：`ahc039` 优化轴对齐多边形，使包围的鲭鱼数减沙丁鱼数最大；`ahc025` 在有限称重后将物品划成总重尽量均衡的组。它们具有硬约束、分数梯度和非平凡搜索空间。论文从强解出发这一点，尤其符合用户“不要用经常一轮恢复完成的任务”的要求。出处为论文 §4.3、附录 B.3/C.3。

预算警戒：150/75/50/30 是代数，不是 token、美元或墙钟总预算；不同领域候选评估成本差异很大。本文没有核实统一费用总表，不据代数直接比较系统效率。官方仓库支持本地或 Slurm 候选评价；当前 README 增加 CLI 模型与新 runner，也不能倒推2025论文已使用这些接口。

**ArcHa 适用性（判断）**：优先挑 ALE-Bench 两道结构不同的题，从公开强解继续优化，保留public/private隔离及每候选时间限制。26圆可用于与现有文献对齐，但解已公开且可直接硬编码，适合做独立构造验证与结果复现，不宜独自支撑“通用科研能力”。AIME scaffold 和 MoE 损失后置，前者评价本身增加LLM调用成本，后者需要训练资源。

## 2. FunSearch：固定求解骨架，进化可部署启发式

主要来源：[Nature原论文 DOI:10.1038/s41586-023-06924-6](https://doi.org/10.1038/s41586-023-06924-6)、[官方仓库 README](https://github.com/google-deepmind/funsearch)、[实际 bin_packing notebook 源码](https://github.com/google-deepmind/funsearch/blob/main/bin_packing/bin_packing.ipynb)。Nature页面最初直接抓取失败，后通过DOI的索引正文读取；没有声称逐页复核补充材料。

论文两类主要任务是 cap/admissible set 构造和 online 1D bin packing。装箱从 best-fit 启发式出发，只进化 `priority(item, bins)`：输入当前物品及剩余容量，返回箱子分数；冻结骨架负责合法箱选择与装入。论文在生成的OR1同规模实例搜索，最终测试OR1–OR4及Weibull不同规模，并与first-fit、best-fit对比。论文指标是相对 **L2下界** 的超额箱数，不能称为相对真实已知最优的差距。

官方notebook公开可检查的小套件：OR3为20例×500物品，Weibull 5k为5例×5000物品；固定评价返回负平均用箱数，并提供装箱合法性验证。notebook展示的是 **L1下界**，与论文L2口径不同；其已保存输出不能当作本轮重跑结果。源码还公开发现的启发式，实验时不能把答案文件同时作为可读任务材料。上述任务接口与数据规模直接由notebook确认。

**开源边界**：官方仓库提供进化逻辑及单线程pipeline，不提供论文使用的生成模型、执行sandbox与分布式基础设施。完整原系统并非开箱复现。本文未核实原论文统一token/费用预算，故不填造数值。

**ArcHa 适用性（判断）**：CPU和NumPy即可评价固定装箱启发式，接入成本低。采用较强best-fit作为起点、增加不同分布/规模的封存测试，比有限参数网格更能区分算法质量；任务仍需先校准，防止只复述公开启发式。

## 3. OpenEvolve：区分作者系统评测与仓库演示

[作者参与的实验文章，2025-08-04](https://huggingface.co/blog/driaforall/towards-open-evolutionary-agents)报告：30个AlgoTune任务、29个实验配置，涉及图算法、线性代数、优化；比较100/200迭代、模型与配置，用各任务加速比的调和平均汇总。具体题包括 `count_connected_components`、`psd_cone_projection`、DCT、SHA256。作者报告同一Flash配置从100到200迭代，汇总分数1.64×到2.04×；这只是作者报告，不是本文复验，也不是同预算单Codex对照。文章的模型token上限属于单次生成配置，不等于端到端累计token。其公开性能解释不宜直接当因果证据。

[Circle Packing仓库演示](https://github.com/algorithmicsuperintelligence/openevolve/blob/main/examples/circle_packing/README.md)同样是26圆半径和最大化，文档描述中途调population、island、prompt等配置，且同时给出两阶段各100迭代的配置和跟踪470代的叙述。不能把这当统一固定预算的标准评测。[Rust sorting演示](https://github.com/algorithmicsuperintelligence/openevolve/blob/main/examples/rust_adaptive_sort/README.md)给出150迭代命令，需要Rust/Cargo。

**已读代码的门限制**：[sorting主程序](https://github.com/algorithmicsuperintelligence/openevolve/blob/main/examples/rust_adaptive_sort/sort_test/src/main.rs)使用随机、近有序、逆序、重复、部分有序五类数据，各1000/10000长度。[Python评价器](https://github.com/algorithmicsuperintelligence/openevolve/blob/main/examples/rust_adaptive_sort/evaluator.py)编译release并读取JSON，以正确性为门、加权性能与适应性打分。但是主程序调用候选库提供的 `run_benchmark`，由候选返回正确性和时间。直接迁移会留下自报成绩路径，ArcHa应采用外部验证与计时。这是源码审阅发现，未实际构造攻击。

**ArcHa适用性（判断）**：优先沿用AlgoTune拥有独立评价的任务，弱化演示目录的“已跑通”证明价值。库替换、JIT、编译缓存是否允许要先写清，否则提速可能来自调用已有实现而非新算法。

## 4. AlphaEvolve：丰富真实任务，部分基础设施不可迁移

[原论文 arXiv:2506.13131v1](https://arxiv.org/html/2506.13131v1)与[DeepMind官方介绍](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)报告三类任务：矩阵乘法张量分解、50多个数学问题、Google计算栈工程优化。具体包括26圆packing、11维kissing number、4×4复矩阵48次标量乘法构造；工程包括数据中心调度启发式、TPU算术电路、Gemini矩阵乘法tiling与编译器生成代码。数学结果及验证材料见[官方结果仓库](https://github.com/google-deepmind/alphaevolve_results)。

数据中心实验用历史工作负载/容量快照作仿真反馈、未见近期数据检验，再部署；论文报告平均回收0.7%全舰队算力。其数据和生产模拟器不能据这段文字认为可公开复跑。硬件/kernel任务依赖Google工具链和设备，不适合作为当前Windows CPU首轮任务。论文的收益值也不等于“相对直接Codex”的收益。

**ArcHa适用性（判断）**：复用公开数学评价器和“先正确性再性能”的任务结构；暂不复制私有生产调度或TPU工程实验。当前调查未取得各任务统一API费/token/墙钟账本，应标未知。

## 5. karpathy/autoresearch：单任务、定候选训练时间

[官方README](https://github.com/karpathy/autoresearch)、[program.md](https://github.com/karpathy/autoresearch/blob/master/program.md)、[prepare.py](https://github.com/karpathy/autoresearch/blob/master/prepare.py)共同定义一个小型单GPU语言模型训练优化任务。agent只改`train.py`，可改架构、优化器、batch和训练循环；`prepare.py`的数据与评价固定。每候选训练300秒，启动/编译不含在这300秒内；目标最小化验证集bits-per-byte。官方要求单NVIDIA GPU，测试于H100，不能假定当前CPU机器可原样运行。

当前源码数据为`karpathy/climbmix-400b-shuffle`；固定validation shard 06542，最大序列长2048、词表8192，验证token常量为`40*524288`。program记录val_bpb、训练/总时间、峰值显存、训练tokens及keep/discard/crash，并给出超10分钟视作失败的操作指引。

**评价边界（判断）**：这是持续优化一个训练任务的简洁基线，不是覆盖多任务的框架benchmark。反复读取同一validation反馈属于开发评价；若要报告泛化优势，应再封存独立test。300秒训练预算也不包含agent推理成本，ArcHa比较要同时累计GPU时、LLM tokens与总墙钟。

## 迁移优先顺序（建议，尚未实验）

1. **ALE-Bench两题**：现成强解继续优化，保留官方judge与private测试。最符合需要长期反馈、难以靠恢复缺失代码完成的需求。
2. **FunSearch在线装箱**：低硬件成本，冻结priority接口与容量合法性，以未见分布/尺寸检验泛化。
3. **AlgoTune少量精选任务**：检验真实程序提速，先确认独立测试/计时与允许依赖，再选有优化空间的强基线。
4. **26圆packing作为文献对齐项**：先解决公开答案/硬编码污染；不能独自支持通用优势。
5. **autoresearch/MoE/GPU kernel后置**：资源可用后再作为训练/硬件扩展项。

跨框架统一比较应使用同模型、工具、起始源码、冻结评价器与资源边界；记录最好有效结果随累计token/墙钟变化。代数、样本数、LLM调用数、训练tokens、agent tokens、API费用是不同预算，不能互换。未达标和失败运行均应保留，单次成功不能证明进化机制优于长会话直接Codex。
