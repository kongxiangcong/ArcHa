# onboard 最小优化与 FT06 回归

日期：2026-10-24，Asia/Shanghai。

最终方案保留 onboard 单次 worker 调用，只修改现有 `opc/scaffold/ONBOARDING.md`。在同一 FT06 基线、brief、map/evidence、模型与推理强度下，最终回归累计 tokens 降低 26.69%，onboard 墙钟降低 49.85%；独立 20 项合同/适配检查及正式 preflight 通过。这是一个任务上的验证，不是统计稳定性或任意项目质量不降的证明。

## 修改范围

- 起草入口先提示阅读范围和完成点；明确字段直接映射，已有门直接复用。
- 有 brief 时复用既有 evidence，只核对影响合同的关键源码，缺口再定向补读；无 brief 的接入仍允许必要调查。
- 补齐 `scratch` 的用途和边界，不增加字段或改变其实现。
- 明确 `{out}/stdout.txt`、`stderr.txt` 属于门执行器；适配器日志使用其他名字。
- 新适配器必须在副本中走一次实际合同门，再验证必要的失败/缺失/陈旧报告语义。起草不运行正式 preflight 或优化。
- 完成合同、context、Open items 与上述验证后结束；复用现有输入保护检查。

未修改 archa-task、brief 模板、onboard Python 调用链、引擎或 worker 配置，没有增加第二次读/写调用、摘要代理、检索服务或运行时限制。仓库原有其他未提交修改保持不动。没有更新已安装技能或现有项目的固定 runtime 快照；本次是源码修改及受控回归。

## 回归控制

历史参照：`ft06-windows-usability-20261024-rerun-02.md`，原项目位于 `D:/dsh-proj/ArcHa.tmp/usability/ft06-20261024-rerun-02/project/ft06-autoloop-smoke`。

- 从原项目 `dc88dc806806f6a0f4c946acc1afa5872d2ee5a2` 恢复接入前源码；不复用生成合同、冠军或优化实现。
- 从接入基线提交 `6581e3b` 恢复原 runtime 与研究材料，核对它们与起草时保存的来源。16 个源码/研究材料文件内容一致；部分文件只有 LF/CRLF 差异。brief、map 和 evidence 的来源摘要一致。
- brief SHA-256：`41f5f2c71f025a720eb1e6a44daefc7805440eefd82a0a112265726165cbe9dd`。
- map SHA-256：`d012384ba20becdc3258809a615f9d917c6785b52d2df410c23a1a3df0a548b2`。
- runtime 保持原版本，只替换本次指南段落，排除当前工作树新增 worker 默认配置等无关变量。
- 历史实际设置取自该 worker 的 session：`gpt-6-astra`、`xhigh`。回归在一次性测试脚本中显式固定相同设置，不改变产品配置。
- 原 CLI 路径已不存在，首次启动未进入模型、tokens=0；保留失败日志。随后使用现存 CLI，报告版本同为 `0.164.0-alpha.11.1`，路径不同，不能证明二进制逐字相同。
- 每个有效试验调用 onboard 一次；全程未重做 archa-task 调研、未补写上游材料，亦未向模型传递旧合同或旧 solver 答案。

本轮使用历史 runtime 做控制变量实验；当前源码的 brief/onboard/worker 与部署链另用既有测试验证。机器运行状态、缓存及模型采样并非完全可控。

## 成本与失败记录

| 指标 | 历史参照 | 首轮指令修改（未通过） | 最终修订 |
|---|---:|---:|---:|
| onboard 墙钟秒 | 592.747 | 584.972 | 297.243 |
| input tokens | 882,986 | 977,698 | 647,665 |
| cached input tokens | 802,816 | 926,976 | 597,376 |
| output tokens | 21,771 | 24,244 | 15,613 |
| reasoning output 字段 | 4,451 | 5,817 | 2,870 |
| ArcHa 总 tokens（input + output） | 904,757 | 1,001,942 | 663,278 |
| 完成的 command_execution | 15 | 19 | 13 |
| 命令返回字符数 | 126,744 | 94,498 | 93,856 |
| 初始 prompt 字符数（LF 归一） | 11,160 | 11,695 | 11,961 |
| 独立实际合同门 | 历史 preflight 通过 | INFRA，日志名称冲突 | 通过 |

tokens 是整个 worker 会话累计量，不是峰值上下文；cached input 是 input 的子集，reasoning 字段单列，不再次加入 ArcHa 总量。本报告不推算金额或订阅额度。

首轮并不成功：返回文本虽然减少约 25%，命令往返增加，总 tokens 反而增加约 10.7%。更关键的是，适配器直接测试通过，却在真实门执行器下因删除其已打开的 `stdout.txt` 而触发 Windows WinError 32。独立结果保留在首轮 `logs/quality-baseline.json`。未手工修复首轮生成合同来冒充起草通过。

据此补齐日志归属和实际合同门验证约定，并提前提示起草顺序、定向补读及停止条件，再从相同起点做第二次独立单调用试验。第二轮自身验证脚本有一次 `broken`/`BROKEN` 断言大小写错误，自行修正，耗时和 tokens 均包含在最终数字中。

最终相对历史：总 tokens 降低 **26.69%**，input 降低约 **26.65%**，墙钟降低 **49.85%**。初始 prompt 实际略长，因此收益不能解释为“少塞了几行提示词”；读取范围、往返和生成内容的减少更符合日志观察，但单样本不能严格归因到某一句指令。

正式 preflight 原为 4.396 秒，本轮为 3.445 秒。onboard + preflight 从 **597.143 秒**降到 **300.689 秒**；上游材料固定、未重跑或加量，preflight 无模型调用，没有把这部分成本转移到 archa-task 或下一阶段。

本次开发验证实际消耗两个有效 worker 会话，合计 **1,665,220 tokens**，不是仅花费最终的 663,278；另有一次零 token 的进程启动失败。表中降幅比较的是最终单次运行，未隐藏试错开销。

## 合同质量对比

| 语义 | 历史合同 | 最终生成合同与独立验证 |
|---|---|---|
| 修改范围 | 仅 solver.py | 相同；源码/研究输入 hash 未变 |
| 冻结评价链 | 原 evaluator、grader、tests 等 | 保留，正式 evaluator digest 含适配器与原链 |
| 生成报告 | scratch，不进入补丁 | 相同 |
| 目标/接纳 | makespan 最小化，严格改善，≤59 停止 | 相同；合法性是约束，59 没有误作逐次接纳约束 |
| 预算 | 6 次、1800 秒、600000 tokens | 相同 |
| R1–R4 | automated / automated / automated / review | ID 与验证类型保留；R4 未冒充自动完成 |
| 合法未达标 | 原 exit 2 → 有效测量 152 | 实际合同门与正式 preflight 均通过 |
| 原单测 | 5 项通过 | 冻结原 unittest 门，独立实跑 5 项通过 |
| 非法候选/语法错误 | 拒绝 | 独立 fixture 实跑拒绝，无有效指标 |
| 缺失/陈旧报告 | 拒绝 | 独立 fixture 实跑拒绝，不复用旧 metrics |
| 原 exit 0 | 接受合法达标测量 | 合成 PASS 协议 fixture 通过；不声称 solver 真达标 |
| 上下文交接 | brief/context 提供给 expert | 相关文件存在且均在默认 20000 字符读取范围内 |
| 起草状态 | 执行关闭，等待提交和 preflight | 相同；独立 check 只有执行关闭/未提交两类问题 |

存在合理的生成差异，不能称逐字等价：

- 合法性指标从 `correct` 改名为 `valid`，requirement、acceptance 与实际指标一致。
- 原单测通过包装器生成 `unit_tests_passed`，新合同直接运行原单测门，不再生成这一指标；R3 的晋升报告会使用 `enforced_per_attempt (no separate check declared)`，而非独立数值 check 的 `met`。这仍符合现有框架，但报告粒度不同。
- expert/designer 的单次 timeout 从旧合同 300/600 秒变为模板的 900/1800 秒，gate timeout 也不同；任务总预算未变，本轮没有验证优化阶段超时行为。

独立检查 **20/20 通过**。仅在隔离回归仓库中，完成审阅后启用执行、提交生成合同，并实际运行 preflight：提交 `1ec2f0501a383ef09c5eb4e2937272594b3c5446`，`ok=true`，无 problems/warnings/degradation，基线 `makespan=152, valid=1`。未启动优化、未调用 expert/designer/reviewer；不把接入回归扩大为算法或最终晋升验证。

现有测试：brief/onboard/worker 配置相关 **52 passed / 1 skipped**（Windows 符号链接权限）；部署 runtime → brief → onboard 链路 **1 passed**。指南 diff whitespace 检查通过。

## 证据位置

- 首轮：`D:/dsh-proj/ArcHa/.tmp/onboard-minimal-20261024/`，保留启动失败、完整 worker 事件、计时与独立门失败。
- 最终：`D:/dsh-proj/ArcHa/.tmp/onboard-minimal-v2-20261024/`。
- 最终 `logs/inputs.json`、`historical-input-equivalence.json`：来源和输入一致性。
- 最终 `project/.opc/local/onboard/onboard-{prompt.md,request.json,events.jsonl}`：实际输入、命令行和完整事件。
- 最终 `logs/final-stats.json`、`onboard-time.json`、`onboard-result.json`：用量、墙钟及返回结果。
- 最终 `logs/draft-*`：执行准备前原样保存的生成合同、context、评价器及 Open items。
- 最终 `logs/quality-summary.json`、`quality-*.json`：独立 20 项检查及逐门原件。
- 最终 `logs/preflight.stdout.json`、`preflight-time.json`：真实冻结基线验证。
- 两目录内 `replay.py`、`quality.py`、`preflight.py` 为一次性回归脚本，未加入生产运行链。

结论范围：这个 FT06 样本的最终方案同时实现了较低的累计用量、较短耗时和通过的接入语义验证。无需继续增加机制；在更多实际任务中复用此指南后再判断稳定降幅。既有 revision 保留、无 brief 接入等分支依靠既有测试/指南规则，本轮未新增真实模型覆盖。
