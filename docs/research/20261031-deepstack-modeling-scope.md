# DeepStack 建模范围核查：S0 需求讨论依据

日期：2026-10-31。固定源码提交：`17e21bf54115e11b9e7c6edc0b2d1723d25d022b`。

本次通过 `git show` 与 `git grep` 读取已提交源码，避开本地未提交改动。阅读论文与关键路径，不安装、不运行、不验证预测精度；这是任务范围核查，不是 S6 的完整研究结果。

## 结论

用户提出的整体流程、硬件架构、执行调度、tiling 和模块建模均有研究价值。DeepStack 面向分布式 LLM 推理的系统—硬件协同建模及设计空间探索，3D DRAM 是重要组成部分。需要同时解释两种架构：被建模硬件的层级，以及软件模型如何分工并传递数据。[论文 v2，2026-04-09，§§3–4](https://arxiv.org/html/2604.04750v2#S3)

但论文总体方法、仓库中存在的能力、某个入口实际走到的实现是三种证据。完整解释应交代它们的对应与差距，不能因为文件存在就认定已接入端到端路径。

## 已读源码与发现

| 对象 | 静态核查所得事实 | 解释边界 |
| --- | --- | --- |
| [GEMM wrapper](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/op_dtype/gemm_wrapper.py) | tiling 包含 thread-block/warp 的 M、N、K 尺寸、stage 数及 row panel。提供指定 tiling、启发式默认值及候选枚举；枚举中比较模型耗时。 | 这是模型评估驱动的搜索，未见该路径实际编译或测速 GPU kernel；搜索范围有限，不能称全局最优。该 wrapper 的 fine/roof 分支为 `pass`。 |
| [wave 资源模型](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/tilesight/tilesight/fused_op_dtype_wave/matmul_fused_op_new_api_wave.py) | GEMM wrapper 实际导入此处 `calculate_matmul_resource_utilization_new`；代码估计资源需求，按架构条件进行 DRAM wave 字节量化，stage 数影响共享内存占用。 | 不能仅凭 wave 命名声称它执行逐 bank 的事务调度。 |
| [共享内存融合汇总](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/tilesight/tilesight/fusion_support/hete_smem_fusion.py) | wrapper 经后处理及寄存器融合调用此函数；函数汇总资源时间，以最大瓶颈项结合 `ceil(waves)/waves` 修正，并加入启动开销，形成延迟与利用率。 | 源码中的解析组合与经验系数是可解释对象；本次未核查系数校准来源或实际精度。 |
| [pipeline-aware GEMM](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/tilesight/tilesight/fused_op_pipeline_wave/matmul_pipeline_wave.py) | 另有公开实现，分解 K 迭代资源、prologue/epilogue，调用 occupancy、pipeline latency 与 wave adjustment。 | 上述 GEMM wrapper 未调用该入口；在 `src/deepstack/mosaic` 与 `src/tilesight` 内搜索 `calculate_matmul_pipeline_wave` 只找到定义。不能因此推断整个仓库无其他调用者，也不能将其当作已经接通的默认端到端模型。 |
| [SwiGLU group-GEMM](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/llm/swiglu/swiglu_coarse_group_gemm.py) | 有 stage 级 compute/communication 组合、group GEMM、激活融合及 collective；根据 overlap 开关选择不同组合方式，stage 3 调用 `get_comp_comm_e2e_time`，末尾累加三个 stage。 | 单芯片流水与跨设备计算通信重叠应分别解释；不能把二者都简称“调度”后省略层级。未运行这些分支。 |
| [bank oracle README](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/bank_oracle/README.md) | 明确说明它是与 coarse performance model 分离的验证 oracle；默认和 demo 是 synthetic toy 配置；可以构造 bank/row/port schedule 及模型下界见证。 | `git grep bank_oracle` 在 mosaic 和 tilesight 源码中无结果，支持“本次未找到主链调用证据”，不证明动态调用绝对不存在。其成功只能证明所设模型内的可达性，不等于真实硬件校准或端到端性能验证。 |

## 整体入口核查（同轮主代理静态阅读）

- [custom_dse.py](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/examples/custom_dse.py)：先检查内存占用与 OOM，再调用 `modeling_decode`，从返回时间计算 STPS。示例搜索 15 组 TP/PP/DP；该入口不进行 kernel tile autotuning。由此可见，“搜索并行方案”与“搜索算子 tiling”是两层不同控制。
- [decode driver](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/dse_space/dse_framework_multi_process_v4_decode_dump_stats.py)：`modeling_decode` 组合 GQA/MLA、FFN/MoE、norm/residual 与 PP 时间，并累计 `ModelPerfStats`。这给出可追踪的端到端聚合入口，但尚未逐模块审计。
- [capacity.py](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/cost/capacity.py)：参考容量接口提供最大 SM 数，不提供面积估算或面积分解。不能把论文面积模型描述当作发行接口直接可观测的输出。

## 对 S0 的需求修正建议

1. **覆盖范围应完整，验证深度可以不同。** 必须交代工作负载、硬件层级、并行切分、单芯片 tiling/融合/流水、计算/存储/网络模型、重叠与总时间汇总，以及 DSE 的目标和约束。未知与未接通机制也属于需要解释的边界。
2. **完整过程不是把所有文件都讲一遍。** 每个模块围绕输入、输出、假设、计算关系、上游与下游作用组织；最终用一条实际入口说明这些关系怎样串起来。
3. **小测试按模块接口与机制疑问拆。** 可分别研究 tiling 如何改变资源需求、并行如何改变 shape/traffic、重叠如何改变汇总时间、3D 参数如何进入存储估计；具体探针留给 ArcHa 自主选择。
4. **不预设论文等于代码。** 需要记录论文主张、固定实现、实际执行三者证据级别，发现路径缺失或实现差异应当如实交付，而不是补写成理想框架。
5. **减法。** 不要求重写 DeepStack、不必运行全量 DSE、不默认还原闭源校准、不把 bank oracle 扩成必做独立项目；只在它能回答主链关键疑问时引入。

尚待 S6 核查：实际可运行环境、各入口开关组合、tiling 搜索结果是否与返回统计一致、系数来源、闭源组件边界、各模块对端到端结果的敏感性。以上静态阅读不足以宣布这些问题已经验证。
