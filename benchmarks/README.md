# ArcHa 评测项目

任务项目与实际实验分开管理。此目录不替代 `opc/tests` 的框架单元测试，关注的是外部项目经过 ArcHa 合同、基线、候选评价、接纳与停止后的表现。

```text
benchmarks/
  cases/<case>/case.json  版本化任务定义、范围、指标和目标
  adapters/evaluate.py    冻结评价器的源文件
  profiles/              模型、推理强度、预算配置
  sources.lock.json      三个上游项目的完整提交 SHA
  requirements.txt       用例实际使用的最小依赖
  projects/<case>/       已生成的基线项目，每个是独立 Git 仓库（不提交父仓库）
  experiments/<id>/      每次实验的独立副本、配置、运行记录和结果
  cache/                 上游源码缓存、隔离虚拟环境和验证临时产物
  reports/               可提交的验证记录
  scripts/               历史 fullflow 执行、费用汇总和报告脚本
  bench.py               准备、复制、计时执行及汇总入口
```

## 四张任务

| ID | 任务 | 唯一可改文件 | 主指标 / 建议目标 |
| --- | --- | --- | --- |
| vliw-pack | 保守 ALU 指令打包 | perf_takehome.py；任务范围仅 build 方法 | bundles ≤1100 |
| kernel-opt | 单核完整内核优化 | perf_takehome.py | cycles ≤74000 |
| ft06-search | JobShopLib 固定计算量参数搜索 | configs/search.json | 三个种子最差 makespan ≤59 |
| riscv-restore | 恢复三个 xDSL RISC-V 规则 | canonicalization_patterns/riscv.py 中三个规则的方法体 | remaining_cases =0 |

来源：[Anthropic performance takehome](https://github.com/anthropics/original_performance_takehome)、
[JobShopLib](https://github.com/Pabloo22/job_shop_lib)、[xDSL](https://github.com/xdslproject/xdsl)。
准确版本见 `sources.lock.json`；原始许可随下载源码保留。Anthropic 只在本地使用修改，候选解不发布、不再分发。

VLIW 冻结测试覆盖独立指令、RAW/WAR/WAW、槽位溢出、非 ALU 屏障、空输入与固定随机序列；比较完整 scratch 和内存。
内核使用上游冻结模拟器，固定单核、工作负载 `(height=10, rounds=16, batch=256)` 和三个数据种子，验证输出后取最大 cycles。
上游完整 `SpeedTests` 包含更高性能档位，不作为基线硬门；“尚未优化”不能被误记为错误代码。

FT06 固定 1000 内层退火步数和 42/43/44 三个种子，验证每道工序、机器互斥与工序顺序后重算 makespan。
只开放邻域、起始和结束温度；不允许换种子或增大步数。内层步数不等于 ArcHa 外层 attempts。
这与之前 `ft06-autoloop-smoke.zip` 的 solver.py 开发任务不同，不能将 152→55 当作这里的基线。

xDSL 准备脚本删除三个已有方法的实现体，形成合法但未完成的基线。冻结评价器验证未知输入、寄存器类型与非零立即数；
其余 AST 必须与上游一致，以防破坏无关规则。三个目标方法允许部分恢复，指标 3→2→1→0。
这是受控功能恢复任务，模型可能已见过上游实现，不用于宣称研究创新；不等价于跑过 xDSL 全量回归。

## 准备与使用（PowerShell）

在 ArcHa 仓库根目录执行。以下命令也可以用 Linux 的虚拟环境 `bin/python` 对应替换。

```powershell
python -m venv benchmarks/cache/venv
benchmarks/cache/venv/Scripts/python.exe -m pip install -r benchmarks/requirements.txt
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py prepare all
```

`prepare` 从锁定的提交导出源码，生成 research-map、task-brief、真实组件和任务合同、冻结评价器及当前 ArcHa runtime 快照，并提交到各自独立 Git 仓库。
模板项目 `execution_enabled=false`。已有项目拒绝覆盖；本机现有基线项目已准备好；新 checkout 需显式准备。目录整理不会重新执行准备或实验。
若本机已存在源码缓存但缺少锁定提交，可在对应缓存仓库 fetch 该提交后重试。

```powershell
# 新建配置固定的实验；不启动模型
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py new vliw-pack --profile codex-medium --id pack-medium-r01
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py exec pack-medium-r01 check
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py exec pack-medium-r01 preflight

# 决定正式测试时才执行；run 会调用模型
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py exec pack-medium-r01 run
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py exec pack-medium-r01 report
# 可选额外审核，单独计成本，不自动应用冠军
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py exec pack-medium-r01 promote
benchmarks/cache/venv/Scripts/python.exe benchmarks/bench.py collect
```

FT06 无模型对照用 `--profile scripted`；开发任务不可使用这个 profile。
`codex-medium` 与 `codex-high` 使用同样模型和预算，仅 expert/designer 推理强度不同。
这些是可编辑的起始实验配置，不保证当前账号有模型权限。要比较其他模型或预算，新增 profile 后新建实验。
不要改已有实验中的 workers.json、合同、runtime 或依赖：执行包装器会拒绝配置漂移。

三阶段对应关系：research-map → task-brief → `.opc` 合同 → check → preflight → run → promote。
这些固定用例已手工接入，日常配置比较无需每轮重新 onboard；若要单独测接入能力，请在新的原始上游副本中使用 archa-map/task/onboard 并单独计费。

## 比较口径

- 一次实验一个独立基线与账本。按同一任务、模板提交、评价器摘要、工具链分组；框架摘要可作为比较变量，但必须显式标记。不同任务的分数不直接排名。
- 至少做 3 个独立重复，报告目标达成率、改善量、时间与 token 的中位数及范围。一次达标也是成功，不强制多轮；失败与 INFRA 记录不能删除或悄悄重跑。
- `summary.json` 保留原始 attempts、champions、charges；`comparison.csv` 汇总状态、停止原因、基线、冠军、attempts、各角色 tokens 和计费时间。
- 命令墙钟包括启动、评价和调度等；角色 `charged_seconds` 是账本口径，不能相加后冒充端到端墙钟。评价器自己的 `evaluation_wall_seconds` 是工作负载耗时，不作为优化目标。
- tokens 是适配器账本计数，不是金额。输入/缓存/输出细分目前不在 charges 中统一存储；需审阅各 worker 原始 JSONL，请勿从总数反推。模型参数见 manifest，实际启动参数见 worker request 记录。
- reviewer 单独列出；run 与 promote 墙钟分别汇总。当前框架 reviewer 可能追加到 run 账本，因此总 tokens 不等于搜索期 tokens。onboard 未执行时是“不适用”，不是一次零成本接入。未知 USD 使用空值。
- 单次有限预算不证明多轮反馈、暂停恢复、INFRA 止损都已经覆盖。这些应作为后续专门实验，保留触发证据。

新目录只存准备和验证，不自动跑付费优化。历史 Windows FT06 已有完整实测，旧对话 `main@cb4ffae` 的环境判断不代表当前版本。

## 源码与本地产物的保留边界

提交 cases、adapters、profiles、bench.py、scripts、tests、依赖版本和审阅后的 reports。cache、projects、experiments 中的运行目录由 .gitignore 排除，包含独立 Git 仓库、账本、原始模型事件与历史候选，整理时保留在本地，不以缓存名义删除。

scripts 中三个辅助脚本针对 2026-10-24 的历史 fullflow；使用本机路径和会话标识，不属于通用运行入口。脚本位置变化后仍指向原 experiments/fullflow-20261024 数据目录。fullflow.py 会启动真实执行；report_fullflow.py 与 collect_auxiliary.py 会写报告。它们均须显式运行，本次整理不执行这些脚本或新的 benchmark。
