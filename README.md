# ArcHa

**ArcHa** 是一个领域无关的自动迭代框架：把一个已经能跑通基线的项目接进来，给一个优化方向，引擎就会反复执行「专家提假设 → 设计者改代码 → 冻结评价器打分 → 确定性接纳 → 反馈下一轮」，直到达成目标、预算耗尽、搜索枯竭或被暂停。

核心不认识 RTL、编译器、模拟器或 PIM bank。领域只通过目标项目 `.opc/` 下的合同和脚本接入：可改范围、冻结的评价器文件、有序命令门、指标字典和一条声明式接纳规则。

目标不是「让分数上涨」，而是让每一次上涨都可复核：候选只能改授权路径、只在干净树上、只由冻结的评价器和工具链打分；缺指标、越界改动、收益落在噪声内都会被拒绝——拒绝同样是结果，会留在账本里。

> 命名：项目现名 **ArcHa**（Python 发行包 `archa-opc`），引擎模块与命令行仍叫 `opc`。早期设计文档中的「Ge」是同一项目的旧称呼，指规划中的统一对话入口；部分文档尚未同步改名。

## 当前状态

- `opc` 引擎 0.3.0：`init / onboard / check / preflight / run / status / pause / stop / report / promote` 均已实现。
- 仓库正从 v0.2 的「合同原型 + 示例」迁到 v0.3 引擎：`contracts/` 与 `examples/` 已从当前工作树移除，本 README 不再引用它们；旧内容见 git 提交 `2eb1dfc`。
- 引擎当前依赖 POSIX 文件锁（`opc/core/ledger.py` 使用 `fcntl`）。请在 Linux、macOS 或 WSL 下运行；Windows 原生 Python 会在导入账本时失败。

## 快速开始

要求：Python ≥ 3.10、Git；目标项目必须是 git 仓库且基线已提交。

```bash
# 1. 安装引擎（在 ArcHa 仓库根目录）
python -m pip install -e .          # 得到 opc 命令；也可 export PYTHONPATH=$PWD 后用 python -m opc

# 2. 在目标项目里生成接入骨架（只写 .opc/，不覆盖、不运行项目代码）
cd /path/to/your-project
opc init -p . --project-id p-demo --name "Demo" --apply

# 3. 按 .opc/ONBOARDING.md 填写可改范围、评价器、门命令、指标和接纳规则
#    也可以让 agent 起草（只允许改 .opc/，越界即失败）
opc onboard -p . --agent codex     # 或 --agent dsh

# 4. 人工审阅合同 → 打开执行开关 → 静态检查 → 提交 → 在基线上真跑一遍门
opc check     -p . --task t-main
git add .opc && git commit -m "opc: onboard"
opc preflight -p . --task t-main

# 5. 跑自动迭代（--direction 覆盖任务合同里的方向）
opc run    -p . --task t-main --direction "先压延迟，面积不许涨"
opc status -p . --task t-main
opc pause  -p . --task t-main      # 在下一个 attempt 边界生效；opc stop 同理
opc report -p . --task t-main

# 6. 晋升审核：复测基线/冠军、检查需求覆盖、可选独立审核；--apply 才会动分支
opc promote -p . --task t-main --confirm 3 --review codex --apply main
```

`opc check` 会把 `execution_enabled=false` 列为问题，所以第 4 步要先打开开关再检查（开关本身也要提交）。

合同进入新 revision 后用 `opc run --new-run`；`--base <ref>` 可从上一次的 champion 接着跑。冠军始终在 `refs/heads/opc/<task>`，只有 `opc promote --apply` 才会快进你指定的分支；若该分支已被检出，promote 只打印合并命令，不动你的工作树。

## 一轮里发生什么

```text
expert ──plan──▶ plan check ──▶ designer ──patch──▶ sandbox ──▶ evaluate
   ▲                                                                │
   └──────────── feedback ◀── champion ◀── accept ◀─────────────────┘
```

| 阶段 | 做什么 | 不通过时 |
| --- | --- | --- |
| EXPERT | 只读 champion 树，产出 ExperimentPlan：假设、要改的文件、预期效果、可证伪条件 | `worker_failed` / 无实验可做即搜索枯竭 |
| PLAN_CHECK | 计划中的文件都在 `editable` 内，且不是重复实验 | 本轮失败，不进入设计 |
| DESIGN | 从 champion **提交**切一棵可写树，设计者实现计划 | `worker_failed`；不改标准 |
| SANDBOX | 逐文件分类改动，任何冻结范围外的改动即失败 | `sandbox_violation` |
| EVALUATE | 只把 `editable` 内的 diff 应用到全新的 champion 树，按顺序跑冻结门 | `broken`（候选问题）/ `infra`（环境问题） |
| ACCEPT | 比较评价器与工具链摘要、约束、目标增益是否超过噪声 | `no_gain` / `incomparable` / 约束拒绝 |
| CHAMPION | 提交、账本先写 intent、CAS 移动 ref、记账 | 恢复时按 intent 对账 |
| FEEDBACK | 把历史、失败原件和剩余预算交给下一轮专家，检查停止条件 | `target_met` / `budget_exhausted` / `stagnation` / `expert_exhausted` |

退出码约定把「候选坏了」和「环境坏了」分开：`0` 通过、`75` 基础设施失败（不消耗搜索次数，连续多次则 blocked）、`77` 跳过（默认拒绝）、其他为候选失败。

## 仓库结构

```text
opc/                     引擎（核心不含量指标名、工具名或领域路径）
  cli.py                 命令行入口
  core/
    engine.py            主循环、停止条件、预算、恢复、视图
    config.py            合同加载与严格校验（未知字段直接报错）
    ledger.py            SQLite 唯一权威账本：run / attempt / champion / 费用 / 控制
    workspace.py         git worktree、sandbox、候选 patch、CAS 移动 ref
    accept.py            确定性接纳：缺指标即拒、约束、噪声下限、自定义规则
    promote.py           晋升：证据链、复测、需求覆盖、可选独立审核、快进
    model.py             值对象（Outcome / Measurements / Cost …）
  domain.py              领域接缝：DomainAdapter 协议与加载
  domains/command.py     默认领域：组件 JSON 里的命令门 + metrics.json
  adapters/              worker 接缝：codex / dsh / scripted + 角色提示词
  strategies/            内置策略（param_search 坐标搜索）
  scaffold/              init 模板、onboard 指令与 ONBOARDING.md
  tests/                 引擎测试（假 codex、假 dsh、失败注入）
tools/project_layout.py  v0.2 时代的接入路径规划工具（独立于引擎，仅预览/生成 .opc 草案）
docs/                    源码核查、历史验证、独立审核、讨论与证据
OPC 框架实现方案.md       设计判断、状态机、预算与恢复、复用选型、分阶段验收
OPC 项目接入与目录规范.md  三个根目录、.opc 布局、实验产物路径与生命周期
pyproject.toml           包元数据（archa-opc 0.3.0，无运行时依赖）
```

目标项目只增加一个 `.opc/` 接入层，源码目录保持原样：

```text
.opc/
  project.json                          项目身份；execution_enabled 默认 false
  ONBOARDING.md                         接入指南（init 复制进来）
  context/PROJECT.md REQUIREMENTS.md DECISIONS.md
  components/<id>.json                  可改范围、冻结评价器、门命令、工具链
  tasks/<task>/revisions/rNNNN/task.json  目标、方向、需求、接纳规则、预算、worker
  eval/evaluate.py                      评测脚本模板：跑项目命令 → 写 metrics.json
  local/                                不入 Git：ledger、原件、视图、本机绑定
```

## 设计要点

- **合同只有一份、严格校验**：`project.json → components/<id>.json → tasks/<task>/revisions/rNNNN/task.json`。未知字段直接报错，拼错的字段不会悄悄失效；`.opc/**` 永远冻结。改合同要开新 revision 和新 run，旧修订不原地改。
- **评价器冻结**：`evaluator_files` 的摘要决定「是否同一个评分器」；工具链版本进入每次测量。摘要不同就不比较新旧数字，工具链变了会当场重测 champion。
- **干净树 + 最小补丁**：评测只接受 `editable` 范围内的 diff，并把它套到从 champion 提交切出的全新树上；忽略文件、缓存、软链和构建产物都不会进入评测。
- **接纳失败关闭**：规则点名的指标缺失即拒绝（不是「没变坏」）；约束必须满足；收益要超过 `max(min_rel_gain, noise_k × 重复测量极差)`。自定义 `acceptance.rule` 必须是冻结评价器文件。
- **单一权威与可恢复**：SQLite 账本是唯一权威，git ref、`STATE.md`、`report.json` 都只是投影；先写 intent 再 CAS 移动 ref，崩溃后按 intent 对账，第二个控制器会被拒绝。
- **接缝可替换**：worker 三选一（`codex` / `dsh` / `scripted`），领域适配器默认是「命令门 + metrics.json」，也可在冻结文件里写 `"adapter": "path.py:Class"`；核心只经两个工厂拿到它们。
- **晋升才做 Spec 轴**：每轮接纳是确定性的，不调用 reviewer；「这个结果是否值得要、结论是否越界」在 promote 时做一次，可选独立审核，未给出可信 verdict 一律阻塞。

## 文档

| 文档 | 内容 | 状态 |
| --- | --- | --- |
| [OPC 框架实现方案](OPC%20框架实现方案.md) | 设计判断、状态机、预算与恢复、复用选型、分阶段验收 | 设计基线；仍用旧名「Ge」，目录示例早于 v0.3 |
| [OPC 项目接入与目录规范](OPC%20项目接入与目录规范.md) | 三个根目录、`.opc` 布局、实验产物与生命周期 | 接入规范；个别链接指向已移除的示例 |
| [opc/README](opc/README.md) | 引擎用法、模块接缝、openTPU 教训、未完成项 | 引擎参考；「已验证」节引用已移除的示例 |
| [接入指南](opc/scaffold/ONBOARDING.md) | 合同字段、评价器契约、退出码、worker 选项 | 当前接入指南（`opc init` 会复制到目标项目） |
| [运行底座核查](docs/research/runtime-reuse.md) / [优化循环核查](docs/research/optimization-reuse.md) | Argus、LangGraph、OpenEvolve 等选型证据 | 选型证据 |
| [项目接入核查](docs/research/project-integration.md) / [GSD 合同核查](docs/research/gsd-contracts.md) | openTPU 目录与生命周期、GSD 需求追踪 | 选型证据 |
| [v0.1 验证记录](docs/validation.md) / [v0.2 接入验证](docs/integration-validation.md) | LangGraph+GEMV 原型、合同 v0.2 与路径工具验证 | 历史记录；引用已移除的 `contracts/`、`examples/` |
| [Standards 审核](docs/review-standards.md) / [Spec 审核](docs/review-spec.md) | v0.1 的双轴独立审核 | 历史记录 |
| [合同审核](docs/review-contracts-v02.md) / [布局审核](docs/review-integration-layout.md) | v0.2 的两项独立审核 | 历史记录 |
| [讨论白板](docs/discussions/opc/winson-whiteboard.md) | 目标边界、减法记录、待验证假设与返回点 | 历史讨论 |
| [证据归档](docs/evidence/) | 上述审核的原始探针与复算结果 | 归档原件 |

## 已知限制

- 只做单任务、串行候选；没有并行资源、多机调度或分布式控制器（Temporal / Argus 仍是待评估选项）。
- 隔离靠 git worktree + worker 沙箱 + 事后越界检查，没有 OS 级隔离（容器、独立账号、只读挂载）。
- 内置 `param_search` 是坐标搜索，会停在局部最优；更强的搜索应作为策略插件接入。
- `dsh` 审核只接受带 `verdict` 键的 JSON；散文评审会被判为「审核不可用」并阻塞晋升——宁可挡住，不可放行。
- `onboard` 只起草合同，不替代人工审阅；`check` / `preflight` 才是就绪判据。
- 文档仍在改名和去旧链接的过程中，设计文档里的 Ge、GEMV、PIM 示例属于历史材料。

## 许可

Apache License 2.0，见 [LICENSE](LICENSE)。

