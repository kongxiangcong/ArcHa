# 开发任务：描述符执行器的 DMA 背压与计算重叠

本任务材料由 ArcHa 维护者人工构造，来源是描述符执行器的常见开发需求；不是厂商 trace、现有真实芯片的校准数据，也不是未解决的上游 issue。它用于一次工程交付试验，不证明大型真实项目适用性或芯片性能精度。

## 需求

起始 `dma_model.py` 已能串行执行拷贝与求和，并提供输入校验和 JSON CLI。将其改为一个有限 DMA 队列、单 DMA 通道和单计算单元的确定性执行器，使 DMA 背压真正影响后续描述符的发射时间，DMA 和计算可以重叠。

用户需要用它观察：改变 DMA 队列深度后，后续计算何时才能开始。无需 GPU、RTL、网络、第三方依赖或厂商数据。

## 接口与输入

保留 `simulate(case: dict) -> dict` 和 `python dma_model.py INPUT.json`。Python 3.10+ 标准库即可。输入结构：

```json
{
  "config": {"queue_depth": 1, "bytes_per_cycle": 2, "setup_cycles": 1},
  "memory": [1, 2, 3, 4, 0, 0, 0, 0, 0, 0, 0, 0],
  "descriptors": [
    {"id": "a", "kind": "dma", "src": 0, "dst": 4, "nbytes": 4},
    {"id": "b", "kind": "dma", "src": 4, "dst": 8, "nbytes": 4},
    {"id": "c", "kind": "compute", "src": 0, "nbytes": 4, "cycles": 2}
  ]
}
```

所有时间单位为抽象整数 cycle，所有地址为字节索引。memory 元素为 0–255 的整数；不模拟地址映射、DDR 行、缓存或总线协议。

- queue_depth 和 bytes_per_cycle 为正整数；setup_cycles 为非负整数。布尔值不是合法整数。
- descriptor 的 id 是唯一非空字符串；kind 为 dma 或 compute。
- src、dma 的 dst 为非负整数；nbytes 为正整数，整个区间必须在 memory 内。
- compute 的 cycles 为正整数，其工作是对源区间的字节求整数和。
- 可选 release 为非负整数，默认 0；可选 depends 为之前描述符 ID 的列表，默认空。只允许依赖先前描述符，因此不存在合法的环。
- 无描述符是合法输入，总周期为 0。非法输入由函数抛出 ValueError，CLI 返回退出码 2；有效 CLI 输出一个 JSON 对象并返回 0。

## 必须遵守的执行语义

1. 从 cycle 0 开始，按输入顺序发射，发射本身不占周期；每个时刻持续发射直到遇到第一个阻塞项。前项阻塞时不得绕过它发射后项。
2. 描述符只在 release 已到、所有 depends 已完成时才能被接受。
3. DMA 队列深度包含正在运行的 DMA 和已接受但尚未运行的 DMA。队列满时阻塞发射；只有 DMA 完成才释放容量。一个通道按接受顺序执行，不抢占。
4. DMA 从 start 到 end 的耗时是 `setup_cycles + ceil(nbytes / bytes_per_cycle)`。数据在 **start 时快照**，在 **end 时写入**；重叠地址按快照拷贝。排队 DMA 不能在 admitted 时提前取源数据。
5. compute 仅在计算单元空闲时接受并立刻开始；不另建计算等待队列。它在 start 时读取并求和，在 end 时公布结果。DMA 与 compute 可以同时运行。
6. 同一 cycle 的顺序：先提交全部完成结果并释放资源，再启动已经排队的 DMA，再按第 1 条继续发射。新接受的 DMA 若通道空闲立即开始。新开始的任务都至少消耗一个 cycle。
7. simulate 不修改调用者输入；每次调用独立。最终输出 events 按原输入顺序排列，每项恰为 id/admitted/start/end；另有最终 memory、以 compute ID 为键的 checksums，以及最后完成时刻 total_cycles。所有数值为整数，字段名称固定，不加性能评分字段。

## 手算验收例子

上面的输入，每次 DMA 耗时 `1 + ceil(4/2) = 3`。

| 深度 | 描述符 | admitted | start | end |
| --- | --- | ---: | ---: | ---: |
| 1 | a | 0 | 0 | 3 |
| 1 | b | 3 | 3 | 6 |
| 1 | c | 3 | 3 | 5 |
| 2 | a | 0 | 0 | 3 |
| 2 | b | 0 | 3 | 6 |
| 2 | c | 0 | 0 | 2 |

两种配置总周期都是 6，最终 memory 都为 `[1,2,3,4,1,2,3,4,1,2,3,4]`，checksums 都为 `{"c":10}`。**只检查总周期或最终内存，会漏掉背压是否真正生效。**

若 c 改为 `src=8, depends=["b"]`，则 c 必须在 cycle 6 开始、cycle 8 完成，结果为 10。若 c 改为 `src=4, cycles=8` 且无依赖、深度为 2，则它在 cycle 0 读到零，结果应为 0，即使 DMA 随后改变了该区域。

## 交付与验收

- 完整实现上述语义，保持函数与 CLI 可用，所有公开例子通过；允许增加自身开发测试。
- 添加简短 README，解释调用方式、队列深度的含义、上述示例及适用边界。不得声称这是 DDR 周期精确仿真。
- 交付可审阅的代码差异与实际验证结果；不要求固定算法、特定代码结构、外层轮数或涨分记录。
- 数值 objective 为 none；时间戳是正确性验收数据，不是要被优化的目标。
- 可修改实现与新增开发测试/README；不得修改 TASK.md、公开 public_checks.py 或外置验收器。新增依赖、改变接口、改变完成条件不属于任务范围。
- 外置终验将使用同一语义下的边界输入和固定种子合成输入。它不增加隐藏需求；不允许寻找或读取其参考实现。

运行公开检查：`python public_checks.py`。起始版本预期有功能失败，这不是环境故障；开始时不需要将失败包装成分数。
