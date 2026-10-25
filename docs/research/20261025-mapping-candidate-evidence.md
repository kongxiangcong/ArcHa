# ArcHa 探索优化候选：源码核对与实验设计

日期：2026-10-25。范围：只读调研；未安装、导入或运行 ZigZag / SCALE-Sim，未执行任何实验。本文是供主实验方案引用的证据材料，不是已运行报告。

## 推荐与减法

首选 **ZigZag 固定架构下、有限成本评价预算的低能耗 temporal mapping 搜索算法开发**。备选 **SCALE-Sim 参考下的快速周期预测模型**。前者已有完整评价器和实质性搜索基线，更容易把“算法迭代”与“建立标签系统”分开。删掉首轮硬件参数联合搜索、跨层融合、完整芯片仿真和真实硅后精度主张。固定硬件与 spatial mapping 后，仍有 LPF 循环次序与逐层存储分配的组合空间，不能预先保证存在可超越 SALSA 的余量。

一个关键前提需要检查：**空间很大，不等于前一轮反馈能继续产生收益**。如果强基线在最低预算已稳定饱和，或者不同 ordering 经分配后几乎都等价，应把该配置判为“研究空间不足”，而非削弱起点或要求至少 N 轮。相反，学习成本模型是另一出发点：即使最优 mapping 不变，减少取得相同质量的搜索成本也可构成有效结果。

## A. ZigZag：候选与版本

- 官方仓库 [ZigZag](https://github.com/KULeuven-MICAS/zigzag)。已通过 GitHub API 核对提交 **`7f9188329368ec72c586ce25f4cb55895171794e`**，作者日期 2026-10-11，版本 **3.9.1**。[版本源码](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/pyproject.toml)。
- 研究来源：[ZigZag 论文](https://ieeexplore.ieee.org/document/9360462/)、[SALSA 原论文，2023](https://arxiv.org/abs/2304.12931)。论文支持这是已有 DNN accelerator mapping 问题；本文任务是基于公开项目重新设计的配对研究，不声称对应一个尚未解决的 issue。
- [安装文档源码](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/docs/source/installation.rst)有 Windows / Linux 两条路径；pyproject 要求 Python >=3.11，含 NumPy、ONNX、multiprocessing_on_dill 等依赖。此为文档/源码证据，不能据此宣称当前机器已可运行。

### 已读源码揭示的基线陷阱

1. [公共 API](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/api.py)的 `opt` 设置外层 reduction，但构造 MainStage 时没有传 `salsa_opt_criterion`；[SalsaStage](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/stages/mapping/salsa.py)和 [SalsaEngine](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/opt/salsa/engine.py)默认内部优化 energy。因此直接给公共 API `opt='latency'` 不能当成正确配置的 latency-SALSA 强基线。
2. [SalsaState](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/opt/salsa/state.py#L73)的 latency 选项使用 `latency_total0`，公共 API 与 stage 比较用 `latency_total2`。**本首选卡因此选择 `energy_total` 作为唯一主优化目标**，延迟单列副指标，不在第一轮混入临时延迟约束。若用户选择延迟目标，需要事先冻结统一 total2 的 adapter，所有对照共享，不能把修正基线目标的收益归给 agent。
3. [LOMA](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/opt/loma/engine.py)的 `limit_lpfs` 会合并质因子；SALSA 源码虽读了 `lpf_limit`，却未执行相同合并。**同一个 lpf_limit 数字不代表同一搜索空间**。实验冻结未合并 LPF 域，LOMA exact check 仅在能完成的同域小实例使用；无法完成时不得称全局最优。
4. SALSA 默认 1000 次迭代、温度 0.05，每次随机交换两个 LPF，依赖 Python `random` 与 NumPy 两套随机源。初始化构造了三个相同 ordering 的 State，State 会调用成本模型；返回后 stage 还会复算。预算不能拿“循环次数”冒充成本模型调用数。准备阶段统一计数实际调用、唯一 mapping、重复请求、非法请求和墙钟；确定性缓存同样向所有臂开放。

以上是源码分析，未执行复现。修复或封装这些入口属于中立实验准备，不是被测试 agent 的成绩。

### 具体任务

真实需求是：部署编译器需在有限编译时间内，为真实神经网络层产生低能耗合法数据流。提交物为可对新层运行的 `search_policy` 算法，不是一张已知网络每层的答案表。

- **冻结**：ZigZag 提交、`MemoryAllocator`、CostModelEvaluation、硬件 cost 表、操作精度、spatial mapping、同域未合并 LPF 集、合法性规则、预算计数器、输入清单和最终评测程序。
- **可改**：temporal ordering 候选生成、邻域、选择/重启机制、合法性预筛、内部排序模型、开发层间知识复用。不得改成本公式、硬件配置、测试清单，也不得按层名字返回硬编码答案。
- **推荐起点**：[edge_tpu_like 硬件](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/inputs/hardware/edge_tpu_like.yaml)与[既有 spatial mapping](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/inputs/mapping/edge_tpu_like.yaml)，现有 SALSA 算法作为可继续改进的 starter。模型名称含 `like`，不能称 Google Edge TPU 真实硬件精确复制。
- **真实层来源**：[ResNet18 YAML](https://github.com/KULeuven-MICAS/zigzag/blob/7f9188329368ec72c586ce25f4cb55895171794e/zigzag/inputs/workload/resnet18.yaml)，以及同提交 `alexnet.onnx`、`mobilenetv2.onnx` 文件。后两者本轮确认树中存在，未解析二进制图；准备阶段须检查受支持 dense Conv 层并保存原图来源/哈希/规范化层清单，不把未支持的层作为零成本。首轮只算提取出的 dense Conv workload 集，不能命名为完整端到端模型优化。

### 正确性、反馈与留出

独立 runner 从算法输出的序列化 mapping 重建 LPF 覆盖、内存分配和成本，禁止信任候选自报能耗。另做小域全枚举、维度重命名不变性和重复评估一致性检查。此处“独立”表示评价程序/进程独立于候选；使用同一冻结 ZigZag 不能证明真实硬件能耗准确。极小数学实例只用于判定器校验，不作主研究任务。

建议开发按模型家族分组：ResNet18 dense Conv 与 AlexNet dense Conv 可见；MobileNetV2 中被明确支持的 dense/pointwise Conv 整族留出。另封存来自真实部署输入分辨率变化的 shape 组；具体分辨率、层列表在准备阶段固定，不在看到两臂结果后挑选。去重规范化 shape：完全相同 `(equation, dims, precision, spatial mapping)` 不跨 split；ResNet18 重复层不能伪装多个独立样本。MobileNet depthwise 层不未经适配自动纳入。若需要 GEMM 跨算子泛化，另立扩展，不混入首轮主分。

反馈可能改变路线的例子：低合法率推动约束引导；合法率高但 mapping 去重率低推动等价类缓存；搜索快速收敛但跨家族退化推动特征/邻域修正；重启收益明显提示局部最优问题；所有方法同能耗则优先降低搜索成本。它们是允许出现的反馈链，不是给 ArcHa 开始后的人工提示，也不能预注册为必须依次发生的轮次。

### 强基线与成本

- 基线为正确配置、同预算的原生 energy-SALSA，开发集允许调优的 SALSA、随机可行搜索作诊断，以及 LOMA 在明确域内的结果。原生与调优基线都保留，不能只挑较弱者。
- 对每个新层相同 oracle 预算与 CPU/内存限制；另报同墙钟结果，避免昂贵排序模型赢调用次数却输总成本。高预算参考是独立且两臂不可见的 best-known，不宣称全局最优。SALSA 已被论文报告具有很强结果，故失败/无改善完全合理。
- 建议预算是**规划上限，不是耗时预测**：每臂一轮研究 pilot 可先设 4 小时墙钟 / 250k 总输入+输出 tokens，先到者停止；没有最少迭代数。搜索器评价预算曲线建议 256、1024、4096 次成本评估，是否可承受须在后续中立准备时测单次 evaluator 的 P50/P95、RAM 和真实实例吞吐后冻结。如果成本过高，应同比例缩小两臂评估规模，而非只减弱基线。
- 准备成本包含依赖锁定、入口封装、映射计数、图到 workload 清单、独立判定器和强基线校准；本轮未测工时。单次候选评价成本约为 `实例数 × 每层预算 × 实测成本评价均耗 + 搜索器开销`，其中均耗未知。

### 公平对照及可审阅结果

两臂共享任务书、starter、依赖、模型/推理设置、文件读取权限、搜索资料、工具、CPU配额和总预算。ArcHa 的前期 map/task/loop 由 Codex 模拟用户，准备 token/墙钟单列并计入端到端成本；启动后外部仅记录。直接 Codex 可自主多轮调查/改代码/测量/保留中间成果，不能被限为一次生成。若模型有多角色上下文或不同并发，按实际总资源计账。

主分可定义为各去重 workload 能耗相对 starter 的几何平均改善，零合法解单独计失败且不从均值悄悄移除；更稳妥的首层报告为成功覆盖率，其次在共同有效集上报告能耗比，并同时列全域失败惩罚结果。记录 latency_total2、搜索墙钟、内存和输出稳定性。共同质量阈值在中立基线阶段确定，未到达标为右删失，不编造成本。

研究过程曲线：每个提交经开发集复验后的最好有效 `Q`，横轴分别为研究累计墙钟、总 token；最终留出只在结束或预注册检查点由外部 judge 测且不向研究 agent 回传。每次报告保存假设、预期、可证伪条件、候选哈希、原始评测引用、观察结果、下一次改动与其关联。优先检查“上一轮哪项证据改变了下一步”，而非计算自然语言里的反思次数。人工修复、环境失败、框架崩溃和无效候选单列，外部不得手改候选或提供优化方案。

## B. SCALE-Sim：备选成本模型案例

版本锁 **`9f98c4371055a54c75209c2e02b640b897550532`**（2025-12-17）；[源码仓库](https://github.com/scalesim-project/SCALE-Sim/tree/9f98c4371055a54c75209c2e02b640b897550532)、[v3论文](https://arxiv.org/abs/2504.15377)。README 声称支持 GEMM、卷积、双缓冲存储和 USER 带宽模式；已读 [single_layer_sim.py](https://github.com/scalesim-project/SCALE-Sim/blob/9f98c4371055a54c75209c2e02b640b897550532/scalesim/single_layer_sim.py)，确实构造 operand/prefetch/demand 矩阵，再经 memory 模型服务请求。未运行。

任务：对来自官方 [Transformer GEMM topology](https://github.com/scalesim-project/SCALE-Sim/blob/9f98c4371055a54c75209c2e02b640b897550532/topologies/GEMM_mnk/transformer_partial.csv)及仓库 CNN/DeepBench 层的 shape，预测冻结 USER 模式的 total cycles（包括预取的字段需统一），用于架构配置排序；可改物理特征、分段/残差模型与有限标签采样；冻结 oracle、配置域、标签预算、评价与数据划分。先只做稠密单核，不接 Ramulator、Accelergy/CACTI 或多核扩展。

强基线包括已校准的阵列解析式、roofline 类瓶颈模型、同标签预算的表格回归器；不只打败常数。注意仓库已经包含 [TPU cycles→time 分段线性模型](https://github.com/scalesim-project/SCALE-Sim/blob/9f98c4371055a54c75209c2e02b640b897550532/scalesim/linear_model/tpu.py)：这不是本任务的 shape→cycles 代理，也不能把它当所有端侧硬件的标定真值。

正确性为独立 frozen simulator 标签、输入域检查、有限非负预测等；效果看 cycles median/P90 相对误差、最差架构组误差、top-k 选型 regret、预测时间和峰值RAM。按网络家族、shape区域、SRAM/带宽配比分组留出，不随机切相邻样本；最终 predict 禁止访问 oracle 或参考标签。标签生成与测量成本计入全生命周期。

多步空间是容量跨越、尾块、填充/排空和带宽瓶颈造成的机制切换；若 roofline/解析式已足够，结果可以是无需复杂模型。大矩阵展开可能使标签成本过高，且这是对软件模型的拟合而非独立硬件验证，故优先级低于 A。建议仍以每臂 4 小时/250k tokens 作初始研究上限提案，标签规模/单次评价耗时待准备期实测，当前不承诺分钟或秒级运行。

## 证据状态

| 内容 | 只读过声明 | 已读源码 | 实际运行 |
|---|---|---|---|
| ZigZag / SALSA 研究动机与论文结果 | 是 | 不等于复现论文 | 否 |
| ZigZag API、SALSA Engine/State/Stage、LOMA、配置与 ResNet18 YAML | 是 | 是，以上固定提交 | 否 |
| AlexNet / MobileNetV2 ONNX | 文件树确认存在 | 未解析二进制图 | 否 |
| SCALE-Sim 支持特性与 v3 论文 | 是 | 部分路径核对 | 否 |
| SCALE-Sim 单层模型、Transformer topology、TPU线性模型 | 是 | 是，以上固定提交 | 否 |

下一步仅供审阅：先确定是否接受 A 的模型能耗目标及冻结单架构/单 spatial mapping 范围，再另行批准中立环境与判定器准备。本文不授权、不启动实施。
