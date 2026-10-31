# Ramulator 2.0 部署与 S0 选题预检

日期：2026-10-31。用户授权部署、跑通和性能资格判断；本次不是 ArcHa 正式考试，也不改变既有 S0 选题。

## 部署

- 路径：`/root/ramulator2`。
- 官方仓库：<https://github.com/CMU-SAFARI/ramulator2>；默认 main 已是 2.1，本次明确使用 `v2.0a`，提交 `be93be78055d922aa1d4d33e15bcc8f2b0c61a9d`。
- GCC 13.3.0，C++20，CMake 3.31.10，Release `-O3 -DNDEBUG`；上游源码未修改。
- 构建工具临时隔离在 `/tmp/ramulator-build-tools`，运行可执行文件不依赖该 Python 环境。首次安装因沙箱 DNS 失败，使用获准的联网命令完成依赖下载。
- 完整环境及依赖提交见 [environment.json](environment.json)。

```bash
/tmp/ramulator-build-tools/bin/cmake -S /root/ramulator2 -B /root/ramulator2/build -DCMAKE_BUILD_TYPE=Release
/tmp/ramulator-build-tools/bin/cmake --build /root/ramulator2/build -j 2
cd /root/ramulator2
./build/ramulator2 -f example_config.yaml
```

## 测量定义

探针 [bench.py](bench.py) 生成确定性输入，固定 DDR4_8Gb_x8、DDR4_2400R、1 channel、2 ranks、Generic controller、FRFCFS、AllBank refresh、ClosedRowPolicy cap=4、RoBaRaCoCh、frontend/memory 时钟比 1:1。64B 对齐、1GiB 地址域、每五个请求有一个写请求，随机种子 20261031。顺序、均匀随机、同 bank 连续换行三种地址分布。

每配置三次新进程、绑定 CPU 0，顺序运行；端到端墙钟包含进程启动、trace 读取、初始化、仿真、统计输出，排除构建及 trace 生成。未清空 OS page cache，不称冷磁盘性能；未对 VM 宿主独占。记录 user/system CPU 时间及每进程峰值 RSS。完整输出去掉前导日志后作 SHA256，以检查重复运行稳定性；这不等于独立正确性证明。

**吞吐定义为成功注入的输入请求数/墙钟秒。** 此版本 LoadStoreTrace 在所有请求被接受后即退出，不 drain 队列。脚本断言 memory-system 的成功读写计数之和等于输入行数；不使用包含重试的 controller 请求计数。保留上游终止语义，没有为了测速修改模型。

同 bank 测试的 262144B 步长来自 64B ×128 columns ×2 ranks ×4 bank groups ×4 banks，按 RoBaRaCoCh 保持 bank/rank/column 固定、改变 row；这是压力负载，不代表典型应用。

复现命令（会重新生成输入并覆盖本目录计时结果）：

```bash
cd /root/ArcHa
python3 docs/reports/ramulator2-preflight-20261031/bench.py
```

trace 默认保存在 `/tmp/ramulator2-preflight`，未纳入 Git，脚本可重新生成；各配置 JSON、原始 stdout/stderr、GNU time 记录、`results.json`、`summary.json` 与 `trace-manifest.json` 保存在本目录。吞吐的分母采用 Python monotonic wall clock，GNU time 的 user/system/RSS 用于辅助判断。只取三次重复，不能视为严密的置信区间估计。

## 证据边界

本次合成负载用于确认成本与重复性，不是 SPEC 应用、完整系统或论文配置复现。官方 SimpleO3 示例只作安装冒烟；其短 trace 循环、LLC 等机制不能代表 DRAM 吞吐。没有运行其他模拟器对照，没有性能优化补丁，不能宣称已证明加速倍数或同行排名。

源码架构、论文对比及等价性风险见 [研究笔记](../../research/20261031-ramulator2-source-review.md)。

## 实测结果

官方 SimpleO3 示例退出码 0，GNU time 墙钟约 0.12s，目标 500,000 条指令，memory system 实际只接受 6 个读请求；只能证明安装可运行。见 `smoke.stdout` / `smoke.time`。

下表为三次新进程中位数（括号内最小–最大），吞吐为成功注入请求数除以中位墙钟时间。

| 负载 | 10万请求 / s | 100万请求 / s | 百万规模注入吞吐 / 请求·s⁻¹ |
| --- | ---: | ---: | ---: |
| 顺序 | 1.863 (1.855–1.973) | 17.878 (17.779–18.062) | 55,936 |
| 均匀随机 | 1.261 (1.247–1.272) | 12.360 (12.357–12.369) | 80,907 |
| 同 bank 换行压力 | 10.876 (10.876–10.910) | 109.345 (109.082–110.892) | 9,145 |

全部 18 次运行成功；每配置三次输出统计 SHA256 一致，成功接收数均等于输入请求数。百万规模峰值 RSS 24.2–24.3 MiB，user CPU 时间接近墙钟，system 时间约 0.02–0.04s。10倍输入对应约9.6–10.1倍耗时，当前范围内近似线性。

顺序输入比随机输入慢是本配置下的测量结果：顺序对应约1259.8万 memory cycles，随机约480.2万，同 bank 约5997.0万。RoBaRaCoCh 连续地址先覆盖同一行/局部 bank，而 ClosedRowPolicy cap=4 会频繁关闭行；这里的地址映射、行策略、银行并行度共同影响成本，不能泛化成“随机访问总是更快”。尚未做策略消融来分解各因素的贡献。

批量成本示例（外推、未实测）：按百万请求、100配置、每配置3次串行运行，随机约1.03小时、顺序约1.49小时、同 bank 压力约9.11小时。真实混合任务、其他硬件或配置不必服从这些数值。

**结论：** 单个小用例不慢，大规模/多配置/冲突负载有显著成本，适合研究等价加速；本轮没有证实可获得的加速倍数。

## S0 适用判断

**适合列为更深入的等价加速候选，但无需宣称它是“低效模拟器”。** 它是 C++20 的周期级 DRAM 模拟器，建模请求队列、地址映射、命令调度、刷新、行状态与时序约束，可以独立读取 trace 或嵌入其他模拟器。其成本来自真实的逐周期推进与状态交互；仅将输入放大制造长时间运行，不足以证明内部存在可消除的浪费。

与现有 DeepStack bank 评估题比较：Ramulator 的单次成本更容易达到十几秒至分钟，调度/背压/刷新交互对正确性更有挑战，完整开源基线也便于独立封装；代价是 C++ 全量编译较重、历史语义和验收面更复杂。二者不计算同一模型，本次耗时差异不能解释为其中一个实现效率更差。

建议首题限定 DDR4、Generic/FRFCFS/AllBank 和冻结 row policy，允许优化软件算法/数据结构，禁止改变时序、队列容量、调度及平局顺序、刷新、请求集合和结束条件。日常公开用例可用 10 万请求，最终验收使用百万请求及不同分布；不必让每轮都运行极端压力负载。

正确性至少冻结全部物理统计；小用例核对逐周期命令序列、地址和回调，较大用例核对统计及确定性摘要。特别注意 upstream 的尾部未排空、重试计数及 buffer 容量边界。若要修正这些语义，应先建立统一的新基线，再开始优化，不能将修正或少算算成加速。

初步可考察重复 readiness 查询、请求复制/分配和层级查询；这些来自源码阅读，**尚未进行热点采样或优化原型验证**。不能承诺加速倍数，也不能把稳定重复结果视为已经建立独立 oracle。本次只推荐候选，不替换已确认的 DeepStack 题面。
