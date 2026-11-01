# S2 统一 Attempt、Worker 交接与运行观察

状态：需求与 grill-with-docs 澄清已收敛，已发布 [S2 实现规格](../../../.scratch/s2-attempts-and-worker-handoffs/spec.md)（ready-for-agent）。规格是行为与验收的权威来源；本页保留背景、说明性例子和核查依据。已发布 [7 张实现事项](../../../.scratch/s2-attempts-and-worker-handoffs/issues/)，尚未实现或启动正式四题考试。

入口：[总规划](../ArcHa_Phased_Development_Plan.md)。整体文档依据：[§8](../ArcHa_Overall_Architecture_and_Task_Policies.md#s08)、[§9](../ArcHa_Overall_Architecture_and_Task_Policies.md#s09)、[§14](../ArcHa_Overall_Architecture_and_Task_Policies.md#s14)。

**依赖：** S1。目标是把“工作尝试”从单一代码补丁和数值结果中解耦。

## 当前焦点：把一轮工作可靠地交出去、收回来、接着做

用户已同意控制复杂度并将 S2 收敛为三个问题：选定工作如何交给 Worker；结果如何保证回到 Expert；中断后如何辨认已完成、未完成和未知，继续执行而不盲目重做。S1 已解决 Run 的契约与恢复入口，S2 补工作级交接与恢复；证据导航细化交 S3，完整接纳/完成策略交 S4。

用户已同意的最小结构是每个 Run 一个逻辑 Expert 上下文，Engine 维护一张以 Attempt 为节点的增量 DAG；Attempt 内沿用 Worker Call、按需评价及既有日志/产物引用，不新增可执行子图、步骤调度语言或外层 Supervisor。跨节点只定义必要输入、结果和依赖，Agent 的局部调试自主完成。独立就绪工作可并行，共享测量资源由 Engine 协调；这不撤销 S0 已确认的并行要求。

反馈保留待处理事实，由 Expert 引用结果并解释；中断恢复先核对持久结果和执行状态，不能把缺少回执当成未执行，也不承诺从任意工具步骤续跑。以下用 revision 起步的完整场景解释交接；具体行为以实现规格为准，尚未实现或开展正式考试。

## 贯通例子：从 revision 到结果交付

**流程已获用户确认（2026-10-31）：** 以下顺利路径及失败、暂停、恢复分支作为 S2 需求依据；交接、在途调用收尾与重试规则已收入实现规格。确认流程不代表实现或验证已经完成。

以下是虚构的小型 CSV 解析器调优任务，不是正式考题或运行证据。用户要求保持指定输入的解析结果不变，在固定负载与测量条件下达到约定加速门槛。revision、Run 的既有规则引用 [S1](../01-task-contracts-and-onboarding/README.md)，不在此另建规格；工作级交接描述 S2 目标行为。

顺利路径：

1. Onboard 将需求整理为候选 `r0001`，明确可修改范围、输入、评价条件、验收与预算，检查工具和材料可用。准备失败可修复同一未冻结候选；ready 不等于已经执行或证明任务完成。
2. 在已有执行授权下，Engine 校验并新建 `Run R1`，绑定并冻结 `r0001`、起始版本与实际配置；累计 Task 用量保留。创建记录本身不启动 Worker。
3. Engine 调用 R1 的 Expert。Expert 选择“定位解析热点”，Engine 据该计划创建 `A1` 并记录派发，再调用 Designer。Designer 在授权内读取、测量、局部调试，返回热点证据，无须制造补丁。Call、输入和原件关联 A1。
4. Engine 保存 A1 结果及用量，保留待处理反馈。Expert 下一次 Call 读取结果，解释热点并选择两个对照方向：`A2` 减少字段复制，`A3` 优化分隔符查找；各自引用同一起始版本及 A1 的必要证据。它们是同一 Run 的工作，不是两个 Run。
5. Engine 增量添加依赖 `A1 → A2`、`A1 → A3`，在输入就绪且资源允许时，使用独立工作区并行派发。Designer 各自实施/自查，必要评价由程序完成；共享 CPU 的正式计时协调执行。局部调试不拆子图或新 Attempt。
6. A2/A3 的代码、评价原件和执行结果保存后交回 Expert，可一次汇集分析。假定 A2 达标、A3 无收益，二者均保留；假设未获支持不等于 Worker 失败。Expert 选择 A2 并建议交付，不将两分支代码自动合并；确需组合时另选工作，才创建依赖相应成果的新 Attempt。
7. Engine 按契约执行必要终验，满足要求后交付并关闭 R1；终验属于交付范围，不强塞普通 Attempt。Expert 建议不能替代验收，最后一轮反馈不能因不再创建 Attempt 而遗漏。完整完成策略仍由 S4 细化。

不顺利时，在同一流程上分支：

| 中断或失败位置 | 应如何继续 |
| --- | --- |
| r0001 准备缺少依赖 | 留在准备流程修复并补查受影响项；不启动正式 Run/Attempt，不新建 revision 掩盖未就绪 |
| A2 的候选未通过正确性检查 | 保存失败候选和证据，反馈 Expert；范围内修复可选为后续 Attempt，仍属 R1/r0001。A3 若独立可继续 |
| 评价器缺工具或测量条件不可信 | 记录执行/测量故障，不据此否定候选或假设；修复后按原条件重新评价并保留旧原件。每次真实测量分别记录并关联原工作，不能把旧缓存标成新实测 |
| Designer 成果已可靠保存，正式评价尚未开始时控制器退出 | 恢复 R1 并核对成果与兼容条件后，从必要评价继续，不重新调用 Designer；不承诺恢复其内部工具执行位置 |
| A2 完整结果已保存，Expert 尚未接收时退出 | 恢复 R1 后仍有待处理反馈，交回 Expert；不重新实施或重测 A2，不重复累计同一次用量 |
| Worker 已派发，但没有可靠终态 | 先核对是否仍运行、已有结果与日志；未查清不能盲目重发。确已失败则保留错误与已知用量，再决定重试或改计划；无法判定则保留未知并阻塞受影响工作 |
| Expert 调用失败或其会话丢失 | 未确认处理的反馈继续保留；从该 Run 的持久材料重建专家上下文再调用，已完成 Attempt 不重做。新的实际调用产生新的用量，不等于旧用量重复记账 |
| 用户暂停 | 保存已发生事实，暂停后不再发起新工作；当前调用在预算与超时内收尾后暂停，不启动下一段。用户继续且兼容时恢复原 R1，先处理遗留事实 |
| 用户 stop 或预算耗尽并关闭 R1 | 不原地重开；如实保留未完成/待分析项。有继续授权及必要预算后创建有依据的新 Run，明确起点及复用成果，累计用量不清零 |
| 用户改变冻结验收，例如更换负载范围 | 准备新 revision，并在开始执行时创建新 Run；旧 R1 仍解释为 r0001。仅换优化假设不需要新 revision；有 r0002 草稿也不自动切换 R1 |
| 最终验收失败 | 保留失败报告，不宣称任务完成；若原 Run 已关闭，沿 S1 的已授权修复 Run 路径继续，不能静默重开或放宽标准 |

本例首先要验证的是：执行结果与研究解释分开记录但能关联，反馈不会丢，恢复不盲目重复执行。DAG 决定哪些工作可继续；不因一个分支失败而无条件中止所有独立分支，也不因节点结束而无条件放行其消费者。

## 规范入口

[实现规格](../../../.scratch/s2-attempts-and-worker-handoffs/spec.md)集中维护工作与角色边界、三处交接、Call/会话身份、恢复重试、暂停停止、DAG 并行、CLI 配置选择、预算和测试验收。不在本页重复维护字段协议或规则副本。

### grill-with-docs：已确认决定

两轮澄清已完成：CLI 切换与 revision、预算重置范围、并行计时和默认并发已写入规格的 Implementation Decisions；此前引用本节的文档以[规格](../../../.scratch/s2-attempts-and-worker-handoffs/spec.md#implementation-decisions)为准。历史实际用量与本次额度扣减起点是不同事实，S1 的历史交付记录不改写。

## 代码与后端能力核查（2026-10-31）

核查基点 `02aeecf8493d970b53e41f804491d9079c6bd594`。本轮只读源码、官方资料和本机 CLI 帮助，未运行模型、测试或考试。S1 的既有回归与贯通证据仍见 [交付记录](../../../.scratch/s1-task-contracts-and-onboarding/spec.md#交付验证)，不能替代 S2 的工作级恢复验证。

### 可复用基础与真实缺口

| 现有入口与事实 | 最小调整 |
| --- | --- |
| [Ledger](../../../opc/core/ledger.py) 已有 SQLite 事务和项目级单写锁；`charge` 没有 Call/测量唯一关联，普通 Run 不能使用现有仅限 preparation 的计量补齐入口 | Engine 统一写账本；派发前分配身份，结果和用量可重复核对而不重复入账，不增加哈希或第二份状态账 |
| [Engine.attempt / reconcile](../../../opc/core/engine.py) 先建 Attempt 再 Expert；返回后才分别记账和保存调用；未完成 Attempt 通常 abandoned | 将 Run 决策与工作执行分开，按已存调用、结果及反馈事实恢复；保留冠军引用收尾能力 |
| `save_conclusions` 允许空反馈，按 `reviewed_by_attempt` 关联；专家材料目录在每轮结束删除 | 用决策 Call 关联处理结果及新工作；专家使用稳定的 Run 级材料入口，保留必要持久材料而不堆积上下文 |
| [Workspaces](../../../opc/core/workspace.py) 同名 checkout 先删除，Engine 的 finally 清理全部工作区 | 仅清理已安全收尾且无恢复用途的工作区；未知在途和未保存成果不能盲删 |
| [Process](../../../opc/core/platform.py) 已管理进程树并可硬终止；Worker 与[评价器](../../../opc/domains/command.py) 同步等待；普通 pause/stop 检查在 Attempt 轮间 | 复用进程管理，加 Call/评价派发前检查和可取消等待；首版无需常驻服务或进程冻结 |
| Engine 缓存 Worker/Domain 对象，候选接纳、评价缓存和冠军状态按串行假设处理 | 不直接并发调用整个 `attempt()`；执行任务独立输入/工作区，主 Engine 汇集结果并串行记账、协调共享资源 |
| [worker_config](../../../opc/core/worker_config.py) 本机字段不含 kind/binary，Engine 恢复冻结 worker_config，但适配器继续读 PATH/OPC_* 环境；准备/终验各有独立选类路径 | 在现有配置模块统一解析四角色实际 WorkerSpec 与来源，新 Run 冻结、恢复复用；保留角色参数隔离，不让 Reviewer 继承 Expert 模型配置 |
| [prompts](../../../opc/adapters/prompts.py) 当前禁止 Expert 查源码/原始日志；Designer 输出主要包装成 summary | 移除与按需证据读取冲突的限制，在授权范围提供可定位原件；只补必要结果/偏差交接，不建设完整 S3 导航系统 |

### 两个 CLI 的核查结论

| 后端 | 已核实 | 尚未验证 / 接入差距 |
| --- | --- | --- |
| Codex CLI | 本机 `codex-cli 0.165.0`；只运行 `--version`、`exec --help`、`exec resume --help`。支持显式 session ID 续接、JSONL、输出 schema；[官方文档](https://learn.chatgpt.com/docs/non-interactive-mode)确认非交互续接与事件输出 | 未调用模型；现适配器只走新会话并把 thread ID 当 Call ID。恢复命令的参数组合、权限保持、真实取消和中断用量仍需轻量实测；不得用 `--last` 猜专家会话 |
| DSH CLI | 当前 PATH 未找到安装；读取官方仓库 `ce7073d51254c26cd63b22a60835b8f948deb447` 的 headless 文档及源码，headless 包版本 `0.2.2-alpha.2`（非本机 CLI 版本）。支持 `--session-id`，校验原 cwd/preset 等，缺会话直接失败 | 未运行 DSH；现适配器没有续接。需固定 Run 专家工作目录。`step_end/turn_end` 事件仍存在，但当前解析器忽略 `final.reason`，应核对本次调用的可靠终态，不能仅凭先前 turn 成功；启动未成功时也须明确记录未执行而非未知计量 |

DSH 固定来源：[headless README](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/bundle/headless/README.md)、[会话采用与最终结果](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/bundle/headless/src/index.ts)、[JSON 投影与用量](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/bundle/headless/src/json-stream.ts)。本机帮助检查成功退出，附带只读环境下无法创建 PATH aliases 的警告；未因此更改安装环境。

两个适配器都须分开 ArcHa Call ID 与后端 session ID，保留本次实际用量和未知项。当前 [Codex](../../../opc/tests/test_codex_and_config.py) / [DSH](../../../opc/tests/test_dsh_worker.py) 主要以假 CLI 测试事件与失败，不证明真实会话恢复或工具隔离。已有进程树管理也不是文件读取隔离；真实工具访问边界与并行工作树必须另行验证。尚未安装 DSH 或发起真实调用，不将缺少运行证据表述为能力已通过。用户随后确认的阶段例外已写入[规格的测试决策](../../../.scratch/s2-attempts-and-worker-handoffs/spec.md#testing-decisions)：DSH 当前只实现，不新增专用测试或真实验证，安装/登录不在本阶段开展；Codex 和公共逻辑仍完成必要验证。

前序取舍依据保留为链接：[S0 原讨论](../../discussions/evaluation/s0-modeling-exploration/winson-whiteboard.md)、[Anthropic 合并子代理文章](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop)、[EAT v1](https://arxiv.org/abs/2610.36848v1)、[LangGraph 持久执行文档源码](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/functional-api.mdx)。它们支持按上下文划分职责、区分组织演化及持久执行边界，不证明 ArcHa 增加 Supervisor 或可执行子图有收益；本轮不新增这些机制。

本阶段使用必要的框架回归、夹具或轻量案例获得反馈；DeepStack 正式建模探索留到 S6。方法变化回写总规划中的测试方法约定，不在此提前运行研究。

下一方向：[S3](../03-evidence-and-shared-knowledge/README.md)。

考试接入要求：所有 Worker 文件读取及执行工具使用题内访问边界，模型通信位于可信外层。现有 benchmark 本地启动器已验证单项目隔离，S2 仍需验证实际 CLI/工具接入与并行工作树；不把仅设置 cwd 当作隔离。
