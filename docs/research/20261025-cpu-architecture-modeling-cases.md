# Windows CPU 条件下的架构建模与映射优化测试案例

日期：2026-10-25。范围：端侧NPU架构/编译器推理评估；无GPU、无RTL仿真器。方法：只读官方源码/文档及用户本地资产，未安装依赖、未运行工具或实验、未修改三个外部项目。GitHub默认分支未锁commit；所有运行时间和目标阈值仍待后续校准。

## 判断

**首选 ZigZag 上的预算化映射搜索算法开发；第二项选择 SCALE-Sim 作为冻结参考的快速代价模型。** 二者分别回答“怎样用有限代价评估找到更好映射”和“怎样更快预测多种架构/shape的模拟周期”。它们允许算法层改进、具有跨实例评价空间；不是复写roofline公式，也不是对几个参数扫完整网格。

没有硬件数据时，冻结的软件参考只是模型内oracle。结果可证明搜索效率或对参考模型的逼近，不能证明真实端侧芯片延迟、功耗、NoC或DRAM时序准确度。

## 一手工具证据与 Windows 边界

### ZigZag：优先核查的可执行后端

- [官方安装文档](https://kuleuven-micas.github.io/zigzag/installation.html)明确包含Windows、Python>=3.11、venv和pip安装步骤。比“Python所以跨平台”有更强文档证据，但本轮没有本机验证。
- [当前pyproject](https://github.com/KULeuven-MICAS/zigzag/blob/master/pyproject.toml)标版本3.9.1、Python>=3.11，依赖NumPy/NetworkX/SymPy/ONNX/multiprocessing_on_dill等。纯Python主体也含有需平台wheel的依赖；须冻结解析结果。
- [公开API](https://github.com/KULeuven-MICAS/zigzag/blob/master/zigzag/api.py)接受workload、accelerator、mapping，支持LOMA/SALSA、even/uneven映射，返回energy、latency和cost-model结果。可用显式workload YAML避免把ONNX未支持算子的零成本回退混进实验。
- [LOMA源码](https://github.com/KULeuven-MICAS/zigzag/blob/master/zigzag/opt/loma/engine.py)枚举loop-prime-factor排列并经MemoryAllocator检查；[SALSA源码](https://github.com/KULeuven-MICAS/zigzag/blob/master/zigzag/opt/salsa/engine.py)使用模拟退火loop-order搜索，有现成强baseline。
- API默认`dump_folder`包含`datetime.now()`字符串；Windows输出目录应显式提供无冒号路径。此为源码可见风险，未复现为运行失败。SALSA多进程spawn、退出清理及种子传递需要单独核查，不把文档可安装等同所有模式已运行。

### SCALE-Sim：核心CPU仿真与外部扩展分开

[官方主仓库](https://github.com/scalesim-project/SCALE-Sim)、[依赖](https://github.com/scalesim-project/SCALE-Sim/blob/main/requirements.txt)及[setup.py](https://github.com/scalesim-project/SCALE-Sim/blob/main/setup.py)说明核心为Python，依赖NumPy/Numba/Pandas/Cython等；setup标OS Independent。没有据此声称本机Windows已验证。旧`scale-sim-v3`仓库明确为legacy，选型应锁主仓库具体版本。

[单层实现](https://github.com/scalesim-project/SCALE-Sim/blob/main/scalesim/single_layer_sim.py)生成operand/prefetch/demand矩阵，再经过双缓冲scratchpad模型计算周期与流量；支持OS/WS/IS。可冻结`COMPUTE_REPORT`中的compute/stall/total cycles及访问量作为参考标签。原工具会展开矩阵与trace，大shape可能耗费很多RAM和时间，不能预设“CPU秒级”。

[CLI源码](https://github.com/scalesim-project/SCALE-Sim/blob/main/scalesim/scale.py)虽解析`-s`，计算`save_space`后构造时仍传`save_disk_space=False`；不能盲信命令行已经关闭trace。后续可采用经核对的Python API `save_disk_space=True`，或冻结一个最小适配器，避免实验中临时改oracle。

[Ramulator集成说明](https://github.com/scalesim-project/SCALE-Sim/blob/main/README_ramulator.md)要求submodule、补丁、make与shell脚本，属于外部C++工具链；Accelergy/CACTI能耗扩展同样另计依赖。首轮只采用明确冻结的内置带宽/双缓冲模型，排除这些扩展，不把其bank/DRAM能力自动算入核心模型。

### AccelForge：有相关资产，Windows成熟度证据较弱

本地`D:/dsh-proj/accelforge`存在Spec、FFM、映射/latency测试及CNN/transformer/多种架构示例。[官方pyproject](https://github.com/Accelergy-Project/accelforge/blob/main/pyproject.toml)还依赖islpy、SymEngine、Numba以及HWComponents的CACTI/NeuroSim等包；Python>=3.8标签不能替代完整依赖可用性验证。本地CI文件只在Ubuntu运行测试，Ubuntu/macOS打包，没有Windows测试证据。

FFM是现成融合/映射baseline；Spec可评估固定mapping，但其代价模型的近似条件必须冻结。当前本地`frontend/model.py`的`_use_new_latency_model`默认False；不可把实验性增强latency路径当默认已启用。适合后续融合DSE研究，首轮优先级低于ZigZag，避免把依赖适配工作当自动科研结果。

## 案例 A：有限 oracle 预算的跨层/跨架构映射搜索

**研究问题**：同样数量的真实代价评估，能否比SALSA和随机/贪心搜索更快找到低延迟或低EDP的合法映射？

**冻结部分**：ZigZag成本模型、MemoryAllocator与合法性判断、硬件结构、每动作成本表、候选时间/内存限制、workload定义和oracle调用预算。输入采用支持的GEMM/Conv张量工作负载；先研究单核多层存储，暂不宣称完整多核NoC、完整LLM decode。

**可改部分**：`search_policy.py`中的候选生成、loop-order邻域、分层搜索、可行性引导、缓存去重和跨已见层初始化等。不是只调SALSA温度；不允许修改cost evaluator、资源约束、种子列表或按具体实例硬编码映射。

**使其足够难**：选择有多个memory levels、uneven temporal mapping和多种spatial mapping的组合空间。开发集中覆盖整齐与非整齐shape，测试留出一组shape族，再留出不同SRAM/带宽配比的架构；不是从同一shape随机拆若干tile当泛化。确认候选空间远大于预算，才能排除扫完整表后选最小值。

**基线**：相同预算SALSA、随机可行采样、固定规则/贪心；小子集用更充分的LOMA参考。LOMA只在明确的LPF合并/映射域内穷举，只有完成枚举的小域可称该域最优；大域参考值称“冻结预算内最好已知”，不能冒充全局最优。

**指标**：独立复算的合法映射比例、延迟或EDP、相对reference的regret、达到同质量所需oracle次数；同时报告搜索CPU时间、峰值内存、总LLM tokens/墙钟及最好结果曲线。能耗来自冻结成本表，只称模型能耗。无收益或超时也保留。

**负担**：无需GPU/RTL，主要是Python成本评估和组合搜索；完整LOMA有阶乘排列风险，不能放进每轮评价。将慢reference预计算与agent实际搜索开销分别计费；时间上限与实例数在接入验证后确定，不承诺当前机器吞吐。

## 案例 B：SCALE-Sim参考下的快速、可泛化 cost model

**研究问题**：在有限参考标签预算下，怎样准确预测shape、阵列形状、SRAM容量、带宽、dataflow变化导致的总周期和stalls，并保留DSE排序质量？

**冻结部分**：锁定SCALE-Sim版本/配置与oracle报告语义；独立标签生成器；开发/留出split；输入域和模型推理的时间/内存约束。单核dense GEMM起步，覆盖容量跨越、tile尾部、计算与带宽瓶颈切换。OS/WS/IS及架构维度要按实验范围明确开放或封存。

**可改部分**：`cost_model.py`中的分段机制、受物理约束的残差修正、特征/拟合方法、不确定性与标签采样策略。训练只使用同一公开标签预算；最终predict阶段禁止调用SCALE-Sim、读取参考标签或展开逐周期trace，防止直接复制oracle伪装快速预测。

**避免退化成公式复写**：roofline/理想阵列解析式本身只是baseline；主测试必须含其无法解释的容量/尾部/访存stalls条件。若这些条件在oracle所选模式下也没有可观测影响，应撤掉相应研究主张。另与同数据预算的简单回归器或现有解析估计比较，不能仅打败一个故意很差的常数模型。

**留出设计**：开发集可反馈误差；测试集同时有未见shape族、未见资源配比及边界shape，封存标签。随机拆分相邻shape仅能测插值。大模型真实拓扑可提供shape来源，但不把只建模GEMM的结果命名为完整端侧LLM端到端性能。

**指标**：总周期相对误差的median/P90/max、零或小stall场景的适当绝对误差、最差架构组误差、排序相关和top-k选择regret；以及推理相对oracle加速比、峰值内存、训练/标签生成成本。单一均值不能掩盖边界失效。

**负担**：参考生成是主要CPU/RAM开销，可先离线缓存后供多轮候选评价；必须把该一次性成本计入建模总成本。正式候选评价在封存标签上运行较快，但本轮没有测量吞吐。标签规模和目标误差需由准备阶段预注册，不能看ArcHa结果后调整。

## 用户资产与不扩大范围

- `D:/dsh-proj/arch-eval-toolchain/README.md`把当前ArchHa明确描述为开源调研/提案，尚无可运行工具链；不能把其预留`src/tests`目录当现成仿真oracle。
- 该项目`docs/research/research-mapping.md`已有固定来源与对AccelForge/Stream/ZigZag的深入边界分析，可复用研究上下文，不用重建一套工具链。当前资产源文件已读，git读取HEAD被本机权限拒绝，因此本轮不填写新的本地commit。
- `D:/dsh-proj/openTPU/README.md`展示真实RTL/ISA/编译器/板卡项目。没有RTL或板卡时只能用其结构、ISA与shape作为需求来源，不能以位精确ISA执行器提供真实硬件周期真值。
- 本轮减法：不建完整芯片模拟器，不接Ramulator/CACTI，不改外部资产，不用小网格参数搜索，不先做完整ONNX/LLM覆盖，不启动任何实验。

## 推荐收口

先选案例A，可直接借现成强搜索baseline与冻结cost evaluator；案例B更贴近性能建模，但要额外承担参考标签与域划分设计。若用户更看重端侧架构预测，先B后A也合理，顺序由研究目标决定。二者都应先交付可审阅任务书、输入域、冻结评价与预算，再启动ArcHa和直接Codex配对执行。
