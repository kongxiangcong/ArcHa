# DeepStack：开发、调优、探索三类模块题的候选核查

2026-10-31。研究基线为 `17e21bf54115e11b9e7c6edc0b2d1723d25d022b`；本轮以 `git show`、`git grep` 只读源码，未运行任何模型、测试或性能测量。本文落实其中开发题与调优题的候选范围；探索题及独立端到端题由主讨论收敛，不在这里伪造已确认需求。

共同约束：三类模块题各自启动，端到端题另起干净任务，不继承前三题代码、解释、知识库或实验成果。共同只共享冻结原始上游版本和已公开任务材料。前三题成功不作为端到端题已完成一部分的证据。

**后续实测更新：** 用户随后授权耗时预检，结果见 [2026-10-31 计时报告](../reports/deepstack-timing-20261031/README.md)。默认 GEMM 较快，但小 tile 与候选扫描存在较高成本；DRAM bank 具有可独立验收的确定性语义和可测热点。当前推荐优先 DRAM bank 等价加速，GEMM/L2为备选，替代下文只读阶段的优先级。尚未实施任何优化、未测得加速倍数。

## 开发题：实现受限拓扑的通信成本模块

**推荐作为开发题候选。** 将已有网络模块抽成独立接口题，隐藏现成实现；这是开发能力测试，不声称 DeepStack 上游缺少该能力。

真实接口来源：[TrafficMatrix](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/noc/traffic_matrix.py) 的 `counts[s,d]` 表示有向流量；[noc_topo.py](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/noc/noc_topo.py) 的 `get_extend_max_routes_with_traffic` 返回 hop 时间、瓶颈链路时间、总时间及物理链路流量。`build_extended_traffic_matrix` 按 `Hierarchy.route` 展开逻辑流量，累加链路字节与路径 hop 延迟。

建议首题缩到单层 ring/mesh，或确有需要时使用明确的两层组合。先冻结：节点编号、路由方向与等距选择、链路是否全双工、流量拆分与取整、空流量/本地流量处理、不可达或零带宽行为。接口可输出规范化有向边流量表，避免要求实现者复制上游内部 extended-index 编码。

验收设计：隐藏的上游实现用于差分参照，另用小图逐流逐边枚举的朴素 judge 独立核对，手算例验证关键语义；上游与独立 judge 不一致时先澄清规格，不能将上游输出自动当真值。公开测试与最终留出包含稀疏/密集流量、多流共享瓶颈、零流量和非均匀链路。主指标是正确性与接口交付，性能只设避免病态实现的门槛。

风险：完整 `Hierarchy.route` 涉及端口展开、交换机中心带宽与路径拆分，直接抄整个接口会使题目过重。只给公式而不公开路由语义则题目不自洽。首题不要求全部六类拓扑、能耗模型或整机 DSE。

## 调优题：固定 GEMM 成本模型的等价加速

**优先推荐为调优题候选，收益空间待实测。** 题目可定为“GEMM 批量成本评估模块的等价加速”：给出完整、可运行且结果冻结的实现，允许改内部计算、数据结构与批处理，要求保持输出语义，目标是减少模型程序自身的 CPU 执行时间。它测建模器实现调优，不宣称加速真实 GPU kernel。不能通过改公式、降低精度、遗漏统计或缩减工作量制造提速。

可抽取边界为 [gemm_wrapper.py](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/op_dtype/gemm_wrapper.py) 的固定 `tiling_config` 下 `get_modeling_time`。它连接 [wave 资源模型](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/tilesight/tilesight/fused_op_dtype_wave/matmul_fused_op_new_api_wave.py)、后处理与融合。冻结公开自有架构参数，避免把私有参考校准变成题目依赖。

独立 judge 在进程外保存基准实现，核对整组返回统计而不只核对耗时标量；浮点容差需先由数值稳定性确定。固定 shape、dtype、tiling、架构域，使用未见输入留出；基准与候选使用同一线程数、进程条件、输入序列，重复计时报告分布及峰值内存。冷热缓存分别计量，禁止靠跨评测答案缓存制造收益；合法缓存需连同构建成本、内存及失效语义一起计入。先用剖析确认热点及基线可重复性，不预设最低加速倍数。

若准备期证明输入规模太小、数值计算本就很快或热点主要在不可改依赖中，应淘汰或调整此候选，不人为削弱基线。作为独立模块题，须保留足够可优化实现与多样输入；不能只剩几个算术表达式。

## 为何暂不把 GEMM tiling 选择列为首选调优题

同一 [gemm_wrapper.py](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/op_dtype/gemm_wrapper.py) 已有启发式默认 tiling 与枚举搜索。`get_tiling_configs_medium` 构造 6×6×1×3 = 108 个候选，再按默认上界与 stage 约束过滤。这个固定小域容易被一次全枚举解决；不能把超过弱默认策略称为有充分区分度的调优能力。

另外，静态源码中枚举分支维护 `best_smem_fusion_post_data`，但返回 `hete_post_data, smem_fusion_post_data, best_config`，前两项来自循环末次计算。此处存在返回统计与最佳配置不一致的风险；未运行确认。若以该接口直接评分可能制造假改善。准备期需核查并固定明确语义，任何候选都应通过固定成本评估器按所返回配置重新评分。若该问题成立，其修复应在基线冻结前对双方统一生效，不能仅将修正统计错配计为调优收益。

若仍选择 tiling 题，需给定有意义的查询/时间预算，固定合法候选域，保留现有启发式及同预算搜索的强基线，以独立穷举结果计算未见 shape 上的选择 regret；最终报告明确“冻结模型内的预测收益”，不当作硬件性能收益。若预算允许穷举全部候选，应承认问题已饱和，不临时扩大域或隐藏信息来制造优势。

## 待准备期确认

- 开发题选择哪一个足够完整又可独立抽取的拓扑域，独立 judge 能否覆盖其语义。
- GEMM 等价加速基线可否独立运行、热点是否具有优化余地、数值容差与测量噪声。
- 三个模块题和端到端题分别有独立 starter、原始证据与运行目录；不把本轮研究答案泄露到探索或端到端任务上下文。

这些都是候选与准备要求，尚未制成可执行题包，也没有实测收益结论。
