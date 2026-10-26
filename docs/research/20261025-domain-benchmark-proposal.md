# ArcHa 领域工程 benchmark 建议：Windows / CPU / 无RTL

日期：2026-10-25。用户最新边界：端侧架构、编译器与推理；性能/架构建模也可；Windows、没有独立GPU和RTL仿真环境；先给方案，不启动实验。数学题、竞赛题退出主候选。

本轮仅源码/文档调查，未安装依赖、编译工具、生成测量数据或执行策略回测。以下是任务设计建议，不是已验证可运行或能达到收益的承诺。它替代[上一轮调研](20261025-self-evolution-benchmark-survey.md)末尾以ALE-Bench/通用算法为主的选题建议，保留前文作为文献事实记录。

## 建议结论

首批两项主benchmark：

1. **实测驱动的CPU推理成本模型**：建立能预测真实推理延迟、辅助实现选择的cost model。
2. **ZigZag预算化映射搜索**：对给定端侧NPU架构，改进tiling/loop-order搜索与选择策略。

**Roll江西铜业逐日策略研究**作为可选第三项真实应用；它可检验数据、假设、代码与结果的闭环，但市场非平稳、目标有风险偏好，不能与前两项的确定性性能结果合成一个总分。

ONNX选择性量化/图优化是推理工程备选；llama.cpp CPU kernel优化待编译链明确后再考虑。SCALE-Sim可以提供软件仿真参考，无需RTL；优先级低于现成Windows说明更明确的ZigZag。

## 证据与本地资产

- ONNX Runtime具有Windows CPU运行入口和Python profiling，后者可输出节点延迟/线程信息；量化收益取决于模型和CPU，可能更慢。[Windows](https://onnxruntime.ai/docs/get-started/with-windows.html)、[profiling](https://onnxruntime.ai/docs/performance/tune-performance/profiling-tools.html)、[量化](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)。
- ZigZag安装文档明确给出Windows/Python>=3.11路径，不只是“纯Python所以应该能跑”；有LOMA/SALSA mapping baseline。[安装](https://kuleuven-micas.github.io/zigzag/installation.html)、[搜索入口](https://github.com/KULeuven-MICAS/zigzag/blob/master/docs/source/getting-started.rst)。尚未本机安装/运行。
- SCALE-Sim支持GEMM、卷积、双缓冲存储和带宽限制；v3的Ramulator/Accelergy扩展增加依赖，不能笼统把全部功能称为Windows开箱可用。[官方README](https://github.com/scalesim-project/SCALE-Sim/blob/main/README.md)。
- llama.cpp官方支持Windows MSVC/clang CPU构建，并有llama-bench。当前PATH未发现cmake/cl/ninja，不能断言本机所有位置均未安装，更不能当已具备编译链。[构建说明](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)、[测量工具](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)。
- 本地`D:/dsh-proj/arch-eval-toolchain`已经研究多核NPU、SRAM/NoC/DRAM资源与映射，但README说明当前仍是提案，不能冒充已有可执行工具链。
- 本地`D:/dsh-proj/accelforge`有真实源码与示例，但依赖islpy/symengine/numba以及hwcomponents-cacti/neurosim等，Windows依赖成本未核实，因此不列第一项落地入口。
- 本地Roll已有日常使用和探索回测，ADR0005明确它们可以独立于正式策略资格交付。不能继续以旧资格流程阻塞全部研究辅助。

协作证据：[Windows推理案例](20261025-windows-cpu-inference-cases.md)、[架构建模案例](20261025-cpu-architecture-modeling-cases.md)、[Roll可行性](20261025-roll-benchmark-feasibility.md)。其中官方支持、源码阅读、本机实跑必须分开标注；本轮没有实跑。

## B1：CPU推理延迟成本模型（第一推荐）

### 真实需求

编译器/部署工具不能对所有shape、精度与实现都完整实测。用有限测量构建cost model，对未测的真实算子/子图预测延迟，并给出较好的实现选择。

候选workload来自小型CNN/Transformer实际图，例如卷积块、MatMul–Add–GELU、attention子图；使用真实层形状及合理的动态batch/序列长度。先选一个runtime、单台CPU，不同时引入跨ISA或跨设备泛化。模型版本、原图与runtime优化后的图都要冻结，不能用toy算子准确率代表整模型预测。

### 输入输出与范围

输入为优化后的图结构、shape、dtype、允许的实现/量化配置与固定CPU/线程信息。输出每个候选的延迟估计与排序；最终预测阶段不能调用计时oracle。ArcHa修改特征、分段机制、模型拟合/组合和采样策略；runtime、计时程序、测试输入和留出数据冻结。

开发数据由独立测量程序生成；若允许主动采样，固定额外测量预算并同时计测量次数与耗时。两条对照使用完全相同的起始数据和资源限制。开发集与留出集按shape区域/子图家族分组，避免只随机拆相邻样本导致虚假泛化。

### 真值、基线与指标

真值为固定runtime配置下的独立端到端计时。profiling用于诊断；开启profiling会影响执行，节点耗时相加不自动等于端到端延迟。记录warm/cold条件、输入分布、线程、重复测量和噪声；本机x86结果只能证明这台机器上的预测。

基线至少包括经同一开发集校准的FLOPs/bytes模型、简单roofline模型与普通表格回归；先比较强一些的基线，不能故意用任意常数制造收益。

- 预测误差：中位相对误差、P90误差；极短延迟另给绝对误差，避免百分比分母放大。
- 决策价值：配置选择regret = 被选实现的实测延迟 / 留出候选中最快实测延迟 - 1。
- 工程开销：预测耗时、模型大小、训练/校准耗时、真实测量次数。
- 成果边界：预测模型准确不等于真实推理内核被加速；决策价值需由所选实现的实测验证。

优势判断：无需GPU/RTL/C++编译，结果贴近编译器成本模型需求；cache边界、融合与shape变化使简单公式可能失效，具有研究空间。尚不能保证当前模型/数据具有足够难度，需先审任务卡而非立即运行。

## B2：固定架构、有限评价预算的映射搜索（第二推荐）

### 真实需求

给定PE阵列、SRAM层次、端口/带宽和精度，为实际层寻找合法的tiling、循环次序与复用策略，在相同搜索资源下找到更低延迟的mapping。

第一版固定硬件，限制为工具已支持的稠密卷积/GEMM类workload；不要同时搜索芯片架构和编译映射。后续才扩展SRAM/阵列/带宽配比，否则难解释收益来自哪里。不同模型家族、shape和少量不同资源配置作最终留出。

### 工具、基线与预算

用冻结ZigZag成本模型评价，先从已有accelerator/workload/mapping输入构造任务。允许修改搜索器、合法性剪枝和候选排序，禁止修改成本公式或硬件规格。

同预算对照包括SALSA、带明确截断策略的LOMA或其他现成搜索，以及直接Codex开发的搜索器。不能声称击败已经穷举完成的同空间最优解；小空间用穷举最优作校验，大空间只报告相对高预算best-known的gap。搜索评价次数与搜索墙钟都报告，单纯回调计数不足以证明严格等CPU计算量。

指标：合法mapping比例、固定功耗/能耗约束下的延迟（也可反向选能耗为目标，但正式运行前只定一个主目标）、达到某质量的评价次数与时间、留出workload的性能/搜索质量。若使用能耗，冻结组件成本参数；不把模型估计当电表实测。

优势判断：与用户架构/编译映射方向高度一致，软件模型给出稳定参考值。它验证的是**冻结架构模型内的优化效果**，不是没有RTL/板卡时的新硬件真实性。

## B3：ONNX CPU选择性量化/图优化（备选）

真实需求是小模型在Windows CPU满足任务精度与内存约束的同时降低推理延迟。允许逐层量化选择、量化边界处理、等价图改写与融合；线程数量固定，避免退化成有限参数网格。

起点应包括runtime完整图优化以及标准量化方案，不能故意关闭现成优化。以实际标签精度作为门，同时看模型大小、峰值内存、端到端P50/P95延迟；只与FP32输出接近不能自动代表任务精度。校准、开发选择与最终测试数据分开。小模型/数据集的具体版本和精度容忍度留在实验卡冻结，不能本轮拍一个“保证提速”的目标。

## B4：SCALE-Sim仿真成本代理（架构建模备选）

用冻结SCALE-Sim的cycles/stall/bandwidth结果作软件参考，构建更快的模型；允许研究边界tile、阵列填充/排空、SRAM容量及带宽瓶颈修正。跨shape与架构配置留出，同时测误差、mapping/架构排序regret、预测速度和需要的oracle调用数。

只选择CPU核心路径，暂不接Ramulator/CACTI/外部RTL。不把直接调用SCALE-Sim再返回结果当快速代理，也不把复刻现成公式当研究成功。参考仿真只能证明对其假设的拟合/近似，不能提供独立硅后精度证据。

## R1：Roll江西铜业逐日策略研究（可选应用案例）

### 目前已有与实际缺口

源码与文档已显示固定SMA5/20的真实探索样例，采用next-open模拟和显式费用/滑点。取数上限120自然日，样例只有81条；除权截窗及预热后回测约2026-08-14至10-23，仅两笔交易。它证明探索流程能运行，不能证明哪种策略最好。[当前说明](D:/dsh-proj/Roll/docs/daily-use.md)、[允许独立探索的ADR0005](D:/dsh-proj/Roll/docs/adr/0005-research-assistance-and-exploratory-backtests.md)。

研究员只读源码还发现一个需验证的评价基础问题：如果按全数据中的最后一个公司行动断点统一截尾，追加未来数据可能让以前的回测段消失。这符合现有演示的截尾契约，不能简单称为实现违约；转向连续研究需改变这项语义。当前是源码推断而非已执行复现；应先检查“未来追加不改变已冻结过去决策/成交”的逐日回放性质。

### 任务如何定义

目标可设为：只用截至决策日可得信息，每日输出目标仓位/维持仓位的条件，按冻结的次日执行模型回放；比较成本后的样本外效果。历史事后最优路径可以作不可达上界，不能作agent能实现的策略承诺。“最优”只在固定风险目标、允许动作与已测方法集合内有明确含义。

先在隔离历史快照与离线模拟账户上研究，复用现有回测基础，不改真实持仓/下单路径。初始对照为现金、买入持有、现有5/20均线；候选可用趋势/波动规则、概率模型或Markov/MDP策略，不预先规定必须用马尔可夫链。

若选择Markov路线，状态可包含趋势、波动、既有仓位与可卖状态，动作先限离散目标仓位；转移概率只从当时可用历史估计，目标明确包含费用与风险。仅有价格涨跌转移矩阵并不能直接推出可执行的买卖策略。

先取得足够长且来源可追溯的量价与公司行动数据，按历史时间滚动训练/验证；最近六个月若尚未用于开发可封存终评，已经看过就标探索样本，不能恢复成未见。价格历史重建与当时真的可获得的新闻/财报分开，不能随意把现时材料补回过去。

交易模型需明确决策/成交时点、未成交、公司行动和费用；A股交收约束及申报单位按时期核对。[上交所2026规则3.1.4/3.3.8](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)。不把日线OHLC中的好价格当保证成交。

指标：未来信息泄漏为零（工程门）、模拟账本一致、扣费后的相对买入持有收益、最大回撤、换手、各滚动窗口稳定性及交易数量。收益没有显著改善也应允许作为研究结论；不拿“必须盈利”迫使搜索反复拟合终评窗口。每日交付可以是“目标仓位＋依据＋改变判断的条件”，不以每日必须交易为目标。

这是独立研究辅助，沿用ADR0005即可；不新增资格审批框架，不将旧正式资格当本case接入的先决条件。

## 对照与下一步

两臂用同源码、模型/推理强度、工具与数据；ArcHa由Codex模拟用户完成map/task/loop准备，启动后由引擎自主推进，外部不手修候选；直接Codex允许自主多轮调查/修改/测试。

同时报告任务结果与研究过程成本：首次讨论/接入、执行期LLM input/cache/output tokens、端到端墙钟、真实测量/仿真次数和时间。成本模型的预测用时、映射求解用时、agent研究用时必须分开。框架修复计干预，不能悄悄补优化思路。

建议下一步只为B1/B2各做一张实验卡，明确数据/参考程序、可改代码、留出划分、强基线和预算；R1若要推进，先界定离线回放与数据补齐的最小范围。本轮不启动这些任务。
