# OPC 候选优化循环：复用调查

核查日期：2026-10-21。范围：用户交接文档中的 OpenEvolve、ShinkaEvolve、openTPU 与 auto-arch-tournament。

结论：这些项目可以复用候选生成、评测反馈、保留胜者和实验记录；不能把它们的 `best`、fitness 通过或 champion 更新直接当作 OPC 的独立审核接纳。先做一个便宜、确定性的编译调度闭环，之后再换成真实模型提案和 RTL/EDA 评测，能够更快定位控制层是否可靠。

## 1. 核查状态和固定版本

本轮经 GitHub connector 读取下面的固定版本 README、部分实现代码和包元数据；没有安装、执行这些项目，也没有复现其性能结果。交接文档记载的旧测试结果不作为本轮实跑证据。另读取了本地 openTPU 的 `docs/tourney.md`，但本地 Git 元数据访问失败，不能据此确认本地 HEAD；下述实现结论以在线固定 SHA 为准。

| 项目 | 固定版本 | 许可证证据 | 本轮状态 |
|---|---|---|---|
| OpenEvolve | 0.4.0，`6a18b3928ccd92898167c0bb27149954ed3e9a9d` | [pyproject](https://github.com/algorithmicsuperintelligence/openevolve/blob/6a18b3928ccd92898167c0bb27149954ed3e9a9d/pyproject.toml) 声明 Apache-2.0 | 已读部分代码；未运行 |
| ShinkaEvolve | 0.0.7，`8adc053a2ce4511ad2ac310e004c530a73fb974a` | [pyproject](https://github.com/SakanaAI/ShinkaEvolve/blob/8adc053a2ce4511ad2ac310e004c530a73fb974a/pyproject.toml) 声明 Apache-2.0 | 已读部分代码；未运行 |
| openTPU | `506e81b1d297e22739dab5ecaeee684493d5c720` | [LICENSE](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/LICENSE) | 已读部分代码；未运行 RTL/EDA |
| auto-arch-tournament | v2 快照 `4c7d42537ae3c8f4f8da778f2c7794a94af73287` | [README License](https://github.com/FeSens/auto-arch-tournament/blob/4c7d42537ae3c8f4f8da778f2c7794a94af73287/README.md#license) 声明 Apache-2.0，并区分 vendored 组件各自许可证 | 已读部分代码；未运行 RTL/EDA |

版本号分别由 [OpenEvolve `_version.py`](https://github.com/algorithmicsuperintelligence/openevolve/blob/6a18b3928ccd92898167c0bb27149954ed3e9a9d/openevolve/_version.py) 和 [Shinka `__init__.py`](https://github.com/SakanaAI/ShinkaEvolve/blob/8adc053a2ce4511ad2ac310e004c530a73fb974a/shinka/__init__.py) 核实。这里是固定快照，不声称它们是最新发行版。

## 2. 可以直接借用什么

| 对象 | 已核查的能力 | OPC 中的位置 | 不能继承的保证 |
|---|---|---|---|
| OpenEvolve | parent/inspiration 选择，LLM diff 或 rewrite，调用 evaluator，metrics/artifacts 回填，程序数据库接纳钩子，checkpoint | `CandidateOptimizer` 插件；给专家提供候选和失败证据 | evaluator 通过不等于独立 reviewer 通过；checkpoint 不证明远端 EDA 作业已对账 |
| ShinkaEvolve | 异步提案/评测，SQLite 记录，Local/Slurm 配置，文本反馈，correct-only best，代数和估计 API 成本限制 | 有大量并行评测后再考虑的候选引擎 | 成本限额不是保守硬预留；恢复代数不等于恢复所有活跃外部作业 |
| openTPU | hypothesis 与 implementation 分阶段，限定可改文件，分级 gates，patch/log/lessons，champion CAS 更新，部分全设计候选重复确认 | 领域适配器的执行/评测流水线参考 | 本地 gate 不等于独立科研审核；估计 fmax 不等于硬件实测 |
| auto-arch-tournament v2 | 固定的 formal/cosim/EDA 评测链，模型只能改约定 RTL 和测试，按性能与面积选择候选 | RTL 领域的评测合同和保护边界参考 | CPU 评测链不能直接变成通用编译器/PIM 研究验收；其工具部署要求仍需满足 |

### OpenEvolve

在 [`process_parallel.py`](https://github.com/algorithmicsuperintelligence/openevolve/blob/6a18b3928ccd92898167c0bb27149954ed3e9a9d/openevolve/process_parallel.py) 中，worker 从数据库快照取 parent、inspirations 和历史 metrics/artifacts，构造 prompt，应用 diff/rewrite，然后执行 evaluator，返回 child、指标、反馈与 token usage。主进程通过 `database.add` 接纳候选并记录 trace。其结构适合包进一个任务节点，不需要将 Ge 改为另一个优化器。

[README 的 population strategy](https://github.com/algorithmicsuperintelligence/openevolve/blob/6a18b3928ccd92898167c0bb27149954ed3e9a9d/README.md#library-usage) 提供 `admit`、`replace_cell`、`archive` 等钩子；但钩子主要决定种群维护，并不是带认证身份的审核签署。建议先使用其现有库入口和 evaluator 合同，避免 fork 主循环。

一个容易出错的适配细节：代码以 `total_iterations = start_iteration + max_iterations` 计算结束点；恢复时把 TaskSpec 的总预算再次传入 `max_iterations`，可能额外启动实验。OPC adapter 必须把剩余 attempt 额度换算成引擎的增量迭代数，并为内部重试单独计账。该结论来自固定版本代码第 644–680 行。

### ShinkaEvolve

[README](https://github.com/SakanaAI/ShinkaEvolve/blob/8adc053a2ce4511ad2ac310e004c530a73fb974a/README.md) 说明 Local/Slurm 评测、SQLite/WebUI、文本反馈与可选 prompt evolution。固定代码的 [`_update_best_solution_async`](https://github.com/SakanaAI/ShinkaEvolve/blob/8adc053a2ce4511ad2ac310e004c530a73fb974a/shinka/core/async_runner.py) 使用 `correct_only=True` 选择 best，适合作为候选过滤，但仍不能替代合同审核。

该文件第 863–886 行计算 `committed_cost = total_api_cost + active_proposals * avg_proposal_cost`；没有历史均值时，在途估计为 0。因此 `max_api_costs` 适合停止继续派发，不能证明最终结算不超限。OPC 需要自己的预算预留、失败计账和未知费用状态，不能只映射这个参数。

同文件第 5018–5021 行从数据库恢复完成代数和下次 generation；这证明持久记录可用于恢复进度，尚不能证明崩溃时仍活跃的 Slurm/local 作业不会重发。本轮没有端到端故障注入证据。`num_generations` 是总代数目标，与 OpenEvolve 的恢复后增量 iterations 不能混用。

### openTPU

固定 [`orchestrator.py`](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/orchestrator.py#L365-L685) 中可以沿调用顺序读到：假设 agent → 实现 agent → sandbox/lint/fast/board/perf/synth → 接纳规则 → 提交胜者 → 用旧 champion SHA 作比较条件更新分支。`hypothesis` 阶段只允许写假设说明；最终记录包含各角色时间、usage、patch 和指标。

固定 [`gates.py`](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/gates.py#L231-L351) 检查 off-limits 路径，并限制通过修改时钟/时序例外等方式提高分数。这是 OPC 必须保留的原则：控制平面、golden、验收程序和评分规则不属于设计 agent 的改动范围。

迁移时建议借鉴字段与流程，不直接拷整个 orchestrator：它依赖现有 Git、构建主机、测试、权重与 EDA 工具，而且“gates 成功”没有自动变成用户要求的双轴独立审核。还要避免将其 worktree 清理、自动提交策略原样变为 Ge 的全局权限。

### auto-arch-tournament v2

固定 [README](https://github.com/FeSens/auto-arch-tournament/blob/4c7d42537ae3c8f4f8da778f2c7794a94af73287/README.md#philosophy) 将 orchestrator、formal、共享评测等放在 agent 修改范围之外；候选 RTL 经过 formal 与 Python ISS cosim。适合复用“固定真值与评测环境、允许演化实现”的流程。

[`tools/eval/fpga.py`](https://github.com/FeSens/auto-arch-tournament/blob/4c7d42537ae3c8f4f8da778f2c7794a94af73287/tools/eval/fpga.py#L330-L389) 将 Gowin 频率与 Verilator CoreMark 的 iter/cycle 相乘形成 fitness。缺少 Logic/Register 计数时返回评测失败，不把缺失资源数当成 0。这正是 OPC 中 `unknown` 不能静默变成最优值的实例。

README 明确说明 V1 的 Yosys/nextpnr 时序模型存在漏计路径问题。因此不能拿历史收益为新 OPC 作真实性背书，也不能混用 V1/V2 的数值。首轮无需引入完整 CPU、Gowin、riscv-formal 链；用户的目标是验证 OPC 能否管理迭代，而非先复现一个 CPU 项目。

## 3. 推荐的最小可行例子

**例子：固定整数 GEMV 语义，探索 row-block 编译调度以减少输入重复加载。** 这是针对 OPC 控制能力的建议实验；下面的数字是可复核推导，不是本研究文件声称已经跑出的结果。实际运行证据应由主实施文档引用本地 run artifacts。

前提：`y[i] = Σ W[i,k]·x[k]`，固定 M、K 和整数语义；编译器生成 LOAD_X/LOAD_W/MAC/STORE trace，独立解释器执行，独立 golden 检查输出。设计 agent 只能改编译调度，不能改解释器、oracle、输入集和指标定义。

对于一次处理 b 行的候选，令 `q = ceil(M/b)`：

```text
X_loads = q * K
W_loads = M * K
Y_stores = M
traffic_elements = q*K + M*K + M
accumulator_slots_required = min(b, M)
```

假设每块遍历全部 K、输入每个 k 在块内复用、没有跨块输入缓存；累加器容量固定为 4。以 M=8、K=64 为训练工作负载：

| 候选 | X 读 | W 读 | Y 写 | 总搬运元素 | 容量合法性 |
|---|---:|---:|---:|---:|---|
| b=1 基线 | 512 | 512 | 8 | 1032 | 合法 |
| b=2 | 256 | 512 | 8 | 776 | 合法 |
| b=4 | 128 | 512 | 8 | 648 | 合法 |
| b=8 | 64 | 512 | 8 | 584 | 超出 4 个累加器，必须拒绝 |

这里的改善来自输入复用，竞争解释是“候选漏算/少读权重”。独立 trace 执行与 golden 对照能区分它们；额外检查 MAC 数恰为 M*K、所有输出写回，能提供更直接的证据。还应加入不整除的 M、K、负数和零值；空维度是否允许要在合同里预先确定。

容量越大越优只是这个固定模型和候选空间下的结果；若真实硬件增加 bank conflict、调度开销或累加器成本，结论可能反转。因此只能报告“指定模型下搬运减少”，不能报告 DDR latency、面积、能量或全局最优。

## 4. 最少需要观察到的闭环证据

1. Ge 冻结 TaskSpec、输入、oracle 和 evaluator 的 hash，计算基线。
2. 专家读取上一轮反馈，产生结构化 ExperimentPlan，含一个可检验假设和资源需求。
3. 设计实现候选、运行开发测试、提交不可变源码与原始日志 manifest。
4. 独立验证调用绑定同一 TaskSpec revision 与 manifest；标准轴审代码/范围，规格轴审整数语义、容量和结果，分别输出 verdict。
5. 确定性接纳规则判定；错误/越界候选不能赢；反馈供下一轮选择。
6. 预算耗尽停止；恢复任务不重置预算；提交内容变化使旧审核失效。

若初版使用确定性提案器或预设 patch，必须标为“工程闭环验证”；若使用真正独立的模型调用，则另列调用身份、prompt/结果、版本和费用证据。两者都不能单独证明开放式科研能力。

## 5. 复用顺序与重新考虑条件

先复用 openTPU/AAT 的合同保护、分级评测、失败记录方法；核心协议由 Ge 掌握。然后只接一个候选引擎：较小的串行/小规模任务优先评估 OpenEvolve；出现大量异步或 Slurm 评测需求时，再评估 Shinka。这个顺序是根据当前集成复杂度作出的工程判断，不是两者搜索质量的实测比较。

暂缓 prompt evolution、多个优化器竞争、整机 CPU/NPU 和 PPA 自动发布。重新考虑的门槛是：同一 TaskSpec 的两轮真实 agent 运行、独立审核、一次拒绝、一次可解释改善、故障恢复与预算停止均有可重放证据。届时再将本例 evaluator 替换为 openTPU 单模块的固定 RTL/仿真/综合适配器，保留原有控制语义。
