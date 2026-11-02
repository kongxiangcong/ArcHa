# Ramulator 2.0 调优题：固定源码与验收边界核查

日期：2026-10-31。本文仅依据本机固定版本源码、随仓库文档和文件状态；没有运行性能实验。耗时与热点需要另行实测。已有的[项目级候选调查](20261031-ramulator2-source-review.md)给出论文比较与初步选题判断，本文补充可执行路径和逐周期等价的验收条件。

## 固定版本与授权

项目位于 `/root/ramulator2`，`origin` 是 [CMU-SAFARI/ramulator2](https://github.com/CMU-SAFARI/ramulator2)。本机 `HEAD` 为 [`be93be78055d922aa1d4d33e15bcc8f2b0c61a9d`](https://github.com/CMU-SAFARI/ramulator2/tree/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d)，`git describe --tags` 为 `v2.0a`，检查时 `git status --short` 为空。根目录的 [`LICENSE`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/LICENSE) 是 MIT 许可；随题分发源码须保留版权与许可声明。本机已有 `build/ramulator2` 可执行文件，但**存在构建产物不等于已验证其运行结果或编译选项**。

## 实际模块路径

随仓库的 [`example_config.yaml`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/example_config.yaml) 选用 DDR4、`GenericDRAM`、`Generic` 控制器、`FRFCFS`、`AllBank` 刷新、`ClosedRowPolicy` 和 `RoBaRaCoCh` 地址映射。不过它的 frontend 是 `SimpleO3`，含处理器前端行为；要隔离内存控制器路径，宜另外冻结 `LoadStoreTrace` 配置与输入。对应的固定源码位置如下：

| 功能 | 固定源码与行为 |
| --- | --- |
| 主循环 | [`src/main.cpp`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/main.cpp)：按时钟比先 `frontend->tick()`，检查完成，再 `memory_system->tick()`。 |
| 系统入口 | [`src/memory_system/impl/generic_DRAM_system.cpp`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/memory_system/impl/generic_DRAM_system.cpp)：地址映射后发往对应通道控制器；系统级请求统计只在 `send` 成功后增加；每个 memory tick 先推进 DRAM，再推进控制器。 |
| 控制器 | [`src/dram_controller/impl/generic_dram_controller.cpp`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/generic_dram_controller.cpp)：接收请求、读转发、读写水位切换、队列优先级、完成回调、刷新、row policy、插件、命令发出、统计。 |
| 调度器 | [`src/dram_controller/impl/scheduler/generic_scheduler.cpp`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/scheduler/generic_scheduler.cpp)：对候选缓冲区的每个请求更新前置命令，再遍历选出最优请求。比较时两边都执行 `check_ready`；就绪者优先，之后按 `arrive` 较早者优先，相等时保留先遇到者。 |
| 刷新 | [`src/dram_controller/impl/refresh/all_bank_refresh.cpp`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/refresh/all_bank_refresh.cpp)：在 `nREFI` 周期为每个 rank 向优先队列送刷新请求。 |
| 命令记录 | [`src/dram_controller/impl/plugin/trace_recorder.cpp`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/plugin/trace_recorder.cpp)：逐通道记录发出命令的周期、命令名和地址向量。 |

控制器一次 `tick` 依序累计队列长度、处理一个到期 pending read、执行刷新、选择请求、更新 row policy 和插件、发命令。选择时先查询 active buffer；若无可发命令，优先队列的首请求即使尚未就绪也会阻塞普通读写请求；之后才按读写水位选择普通缓冲区。关行命令还要检查 active buffer 是否有匹配 row group。这些先后关系都直接影响命令周期和统计，不宜把“FRFCFS”名字当成完整调度规格。来源同上控制器和调度器。

## 等价优化的可验收性

“请求接收行为不变”须比较**每次送入尝试的周期、请求身份和布尔结果**。[`LoadStoreTrace::tick`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/frontend/impl/memory_trace/loadstore_trace.cpp) 只在 `send` 成功后前进；系统级统计只能证明成功总数，不能证明逐周期背压相同。现有 `TraceRecorder` 能核对命令发出周期、顺序与地址，包括刷新相关命令，但不记录接收尝试或回调。若题面要求严格接收与回调等价，需先做独立、冻结的验收记录器或在评测 harness 中记录 `send` 的输入/结果及回调周期；该 instrumentation 对基线与候选必须一致，不能把它算作考生优化。

统计须逐项比较：系统级周期与成功请求数、控制器的尝试请求数、队列长度积分及均值、读延迟、行命中/缺失/冲突等。控制器的 `s_num_read_reqs` 等在尝试入队前增长，因此失败重试也会增加；与系统级成功请求数不应混为一谈。[控制器源码](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/dram_controller/impl/generic_dram_controller.cpp)、[系统源码](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/memory_system/impl/generic_DRAM_system.cpp)。[`ReqBuffer::enqueue`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/base/request.h) 的条件是 `size() <= max_size`，会允许名义容量再多一个请求；这是固定版本行为，不能在优化时顺手改掉。

`LoadStoreTrace` 在全部输入**成功送入**后完成；主循环在其完成检查之后不再调用 memory tick，因此尾部请求未必完成。若原样使用，题面必须把结束定义为“注入完成”，不要写成“请求全部完成”。[`ReadWriteTrace`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/frontend/impl/memory_trace/readwrite_trace.cpp) 的 `is_finished()` 恒为 `true` 且忽略 `send` 结果，不适合作为现成的等价验收前端。现有 [`src/test/test_impl.cpp`](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/src/test/test_impl.cpp) 是实现工厂示例，不是控制器/调度器等价测试。[README 的 Verilog verification 章节](https://github.com/CMU-SAFARI/ramulator2/blob/be93be78055d922aa1d4d33e15bcc8f2b0c61a9d/README.md) 可验证命令时序合法性，但不能代替候选与基线的逐周期等价比较。

## 对 S0 题目的建议

这个题目比纯成本估算更适合承载“调优”场景：它有真实 C++ 逐周期热路径、可调输入规模，以及接收、命令、刷新、统计四层可观察约束。这里是**基于源码的选题推论**，不是已测出的优化潜力或运行时长。建议冻结上面的提交、DDR4 标准和相关配置，允许改 `Generic`/`FRFCFS` 路径，验收覆盖顺序流、随机、同 bank 行冲突、读写混合、背压和至少一次刷新。设置 trace 长度时必须确认仿真实际越过 `nREFI`；详细日志用小负载比对，计时关闭日志。性能是否有足够挑战性，应以主任务独立测出的基线墙钟时间和 profiler 热点为准。
