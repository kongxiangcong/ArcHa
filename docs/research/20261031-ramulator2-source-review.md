# Ramulator 2.0：源码与选题资格核查

日期：2026-10-31。范围：官方论文、固定版本源码与 S0 需求对照；本文不包含本机性能测量，也不声称已实现加速。部署与测量由本轮主任务另行记录。

## 判断

Ramulator 2.0 值得作为**保持仿真行为等价的软件加速候选题**：真实逐周期状态机、调度和刷新交互提供了足够的正确性约束，输入规模可以自然放大。但“它在同类中很慢”和“容易得到显著加速”都没有证据。论文的同条件比较反而显示它具有竞争力；本机运行时间、热点占比和可重复性应决定是否采用。

这与当前 S0 的“DRAM bank 评估器等价加速”目标相容，但不是同一研究对象。现有 [S0 入口](../architecture-and-task-policies/00-foundations-and-test-methods/README.md) 和 [讨论白板](../discussions/evaluation/s0-modeling-exploration/winson-whiteboard.md) 仍登记 DeepStack 方案；本次只是考察候选，不替用户宣布替换，也不代表 S0 完成或正式考试开始。

## 版本与论文证据

当前官方 `main` 的 README 已是 Ramulator **2.1**，不能把直接克隆默认分支所得版本称为 2.0。官方保留 `legacy/v2.0a`；本轮固定源码为 `be93be78055d922aa1d4d33e15bcc8f2b0c61a9d`，本地位于 `/root/ramulator2`。[当前仓库](https://github.com/CMU-SAFARI/ramulator2)、[固定版本 README](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/README.md)

论文 v2 的表 I 使用 gcc-12 `-O3`、Xeon Gold 5118，每条 trace 500 万请求、读写比 4:1、10 次运行；下列是论文均值，**不是本机结果**：

| 模拟器 | Random 墙钟秒 | Stream 墙钟秒 |
| --- | ---: | ---: |
| Ramulator 2.0 | 50.6 | 26.2 |
| Ramulator 1.0 | 59.0 | 31.9 |
| DRAMsim3 | 51.7 | 37.8 |
| DRAMsim2 | 51.9 | 53.9 |

Ramulator 2.0 对应约 98.8K/190.8K 请求每秒，说明大规模逐周期模拟有显著成本，但不足以称它比同行慢。[论文 §III-B、表 I](https://arxiv.org/html/2308.11030v2#S3.SS2)

## 固定源码揭示的运行方式

以下均来自本地固定提交的源码检查；链接指向同一提交。

- **执行路径**：主程序按 frontend/memory system 的相对时钟推进；请求经地址映射进入控制器，调度器查询 DRAM 前置命令和就绪条件，控制器发命令后推进设备状态。控制器每 tick 还处理完成回调、刷新、row policy、插件和统计。[main.cpp](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/main.cpp)、[Generic 控制器](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/generic_dram_controller.cpp)
- **FRFCFS 的实际比较规则**：先对 buffer 每个请求算前置命令，再遍历比较；比较两端分别调用 `check_ready`，就绪优先，其次 `arrive`，相等时保留先遇到者。不能根据策略名字擅自换成另一种“标准 FRFCFS”。[generic_scheduler.cpp](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/scheduler/generic_scheduler.cpp)
- **容器和查询成本**：请求 buffer 是 `std::list<Request>`，请求含动态地址向量和 callback；DRAM 的就绪检查与 timing 更新沿层级节点执行。这些是可供 profiler 核查的机制，不是已测出的热点。[request.h](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/base/request.h)、[node.h](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram/node.h)

## 测速和等价验收的关键陷阱

1. **LoadStoreTrace 不排空尾部。** 它在成功送入全部 trace 请求后返回 finished；主循环先 frontend tick，再检查结束，再 memory tick。因此请求数/墙钟时间应标成“输入请求注入吞吐”，不能标成“全部请求完成吞吐”。默认退出行为可以作为固定基线保留，但验收必须明确；若要 drain，需先统一修改基线和实验定义，不能把改终止条件算成提速。[loadstore_trace.cpp](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/frontend/impl/memory_trace/loadstore_trace.cpp)、[main.cpp](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/main.cpp)
2. **请求统计不是处处等于成功请求数。** Generic 控制器在尝试 enqueue 前增长读写请求计数，失败重试也会计入；memory-system 侧、controller 侧和 trace 计数不能混用。read forwarding、读写模式阈值、priority queue 阻塞与 active queue 优先级也属于现有行为。[Generic 控制器](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/generic_dram_controller.cpp)
3. **历史边界行为必须冻结。** `ReqBuffer::enqueue` 使用 `size() <= max_size`，会允许比名义上限多一个请求。将它顺手改成 `<` 会改变背压和结果，属于修正模型行为，不能混进等价优化。[request.h](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/base/request.h)
4. **示例跑通不能代表大负载性能。** SimpleO3 还包含指令窗口、LLC 和翻译，按各 core 达到目标指令数终止；其吞吐不能直接当纯内存模拟吞吐。[simpleO3.cpp](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/frontend/impl/processor/simpleO3/simpleO3.cpp)

## 候选优化空间与适用边界

下面是基于上述实现的**待验证推论**，没有实测收益承诺：

- 同一次调度扫描中减少重复的 readiness 查询，保持前置命令计算、比较优先级及平局顺序；不能未经证明就跨 tick 缓存，因为时钟与刷新会改变就绪性。
- 优化请求复制、分配和容器局部性，保留 iterator、删除、遍历顺序及 callback 行为。数据结构替换比局部消冗余的正确性负担更大。
- 研究减少无事发生周期的推进成本，但必须精确补齐刷新、回调、队列长度积分、插件更新和多时钟先后顺序；不建议把泛化事件驱动重写设成首版必需目标。

建议首版边界固定为一个 DRAM 标准、Generic 控制器、明确的调度/刷新/row policy，涵盖流式、随机、同 bank 冲突、读写混合与背压；其余标准和 RowHammer 插件只有在实际任务需要时加入。单进程运行时间足够稳定且处于秒到几十秒时，既能测出收益，也能容纳多次实验。

正式验收至少比较周期数、请求统计、行命中/冲突、延迟等完整统计，并在小负载比较带周期和地址的命令序列及必要回调；总体平均延迟相同不足以证明逐周期等价。命令日志会改变计时成本，应将详细正确性记录和计时分开。固定 Release 编译器与选项、线程和资源条件，预先规定初始化/读 trace 是否计时，保留原始输出及重复运行离散度。没有优化原型及独立验收前，只能判定“有成本、值得候选”，不能保证某个加速倍数。
