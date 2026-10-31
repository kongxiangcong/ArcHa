# OPC 接入指南（人和 agent 共用）

本文件由 `opc init` 复制到 `.opc/ONBOARDING.md`，也是 `opc onboard` 交给 agent 的指令。
目标：把一个**已经能跑通流程的基线项目**接入 OPC，使它可以被自动迭代优化。

起草时先按第 6、7 节确定读取范围与完成点，再用第 2–4 节填写合同。简报和模板已明确的字段直接映射，已有可用门直接复用，适配层只处理项目与门协议的差异。

## 0. 先确认四件事，缺一件就不能开始自动迭代

| 必需 | 含义 | 放在哪里 |
| --- | --- | --- |
| 可改范围 | 迭代只允许修改哪些文件（配置、源码、RTL…） | `components/<id>.json` 的 `editable` |
| 冻结评价器 | 把一棵源码树变成数字的全部东西：测试、参考/golden、评测脚本、工作负载 | `evaluator_files`（必须已提交） |
| 基线数字 | 当前提交跑评价器得到的指标 | `opc preflight` 自动测 |
| 接纳规则 | 什么叫"更好"、哪些约束不能破 | `tasks/<task>/revisions/rNNNN/task.json` 的 `acceptance` |

没有评价器时，第一件事是**建评价器**，不是开始优化。

## 1. 目录（`opc init` 生成）

```text
.opc/
  project.json                 项目身份；execution_enabled 默认 false，审完合同再打开
  ONBOARDING.md                本文件
  context/PROJECT.md           项目是什么、已有能力、边界
  context/REQUIREMENTS.md      带编号的需求（REQ-001…），写清验收证据
  context/DECISIONS.md         已定决定 / agent 可自主 / 延期
  components/<id>.json         组件合同：可改范围、评价器、门命令、工具链
  tasks/<task>/revisions/r0001/task.json   任务合同：目标、方向、接纳、预算、worker
  eval/evaluate.py             评测脚本模板：跑项目命令 → 写 metrics.json
  local/                       不入 Git：ledger、原件、视图
```

## 2. 写评测脚本 `.opc/eval/evaluate.py`

它在一棵**干净的候选树**里运行（cwd = 树根），做三件事：

1. 运行项目已有的流程（仿真、编译、综合、benchmark…）。
2. 检查正确性（对 golden / 参考模型），不正确就以非 0 退出。
3. 把指标写进 `--out` 目录下的 `metrics.json`：`{"metrics": {"latency_cycles": 1234, "correct": 1}}`。

`{out}/stdout.txt` 和 `{out}/stderr.txt` 由门执行器持有；适配器自己的子进程日志使用不同名称（如 `original-stdout.txt`），避免覆盖或删除门日志。

退出码约定（区分"候选坏了"和"环境坏了"——openTPU 曾把环境故障记成候选失败）：

| 退出码 | 含义 | OPC 的处理 |
| --- | --- | --- |
| 0 | 通过 | 读取指标 |
| 75 | 基础设施失败：工具缺失、许可证、磁盘、数据不可用 | 记 INFRA，不消耗搜索次数；连续多次则 run 进入 blocked |
| 77 | 跳过：该门无法运行（例如缺权重） | 默认拒绝；`on_skip: degrade` 时允许但标记证据降级 |
| 其他 | 候选导致的失败 | 记 BROKEN |

## 3. 组件合同 `components/<id>.json`

合同没有版本号，字段集合就是下面列出的这些。不认识的字段直接报错（拼错的字段不会悄悄失效）；以 `_` 开头的键可以写备注。

```json
{
  "component_id": "emu",
  "description": "一句话：这个组件做什么、优化什么",
  "editable": ["configs/emulator.json"],
  "frozen": ["tests/**", "golden/**"],
  "evaluator_files": [".opc/eval/**", "tests/**", "golden/**", "workloads/**"],
  "scratch": [],
  "toolchain": [["{python}", "--version"]],
  "gates": [
    {"id": "unit", "argv": ["{python}", "-m", "pytest", "-q", "tests"], "timeout_s": 600},
    {"id": "evaluate", "argv": ["{python}", ".opc/eval/evaluate.py", "--out", "{out}"],
     "metrics": "{out}/metrics.json", "timeout_s": 3600, "repeat": true}
  ],
  "context_files": [".opc/context/PROJECT.md", ".opc/context/REQUIREMENTS.md", ".opc/context/DECISIONS.md"],
  "focus_areas": []
}
```

规则：
- `editable` 越窄越好。不在 `editable` 里的路径本来就不可改；`frozen` 只用来从 `editable` 的通配里挖掉例外（如 `src/**` 里的 `src/golden/**`）。与 `frozen`/`evaluator_files` 冲突时拒绝优先；`.opc/**` 永远冻结。
- 调参任务里，被调参的模型/模拟器代码本身就是评价器的一部分，要列进 `evaluator_files`：候选能改模型，就等于能改评分。
- `evaluator_files` 决定 evaluator digest：任何一个文件变了，就是新的评价器，必须开新 run。
- `scratch` 声明命令生成的文件（如评测报告）：允许生成，但不进入候选补丁；冻结评价器和 `.opc/**` 仍受保护。只列实际生成物，与可改源码分开，不扩大 `editable`。
- `toolchain` 列出会影响数字的工具版本命令。工具链变了，champion 会被重测，不同工具链的数字不比较（openTPU 上 Yosys 0.69/0.70 让 fmax 差 14.8%）。
- 门按顺序执行，首个失败即停。占位符：`{worktree}` 候选树、`{out}` 该门输出目录、`{python}` 当前解释器。
- 不要用 `sh -c`：把命令写成评价器里的脚本。
- `deterministic: true`：同一源码 + 评价器 + 工具链必然得到同一数字时才打开，打开后评测结果按这三者缓存。综合/布局布线/有随机性的仿真不要打开。
- 机器相关路径（工具安装位置）不要写进合同；在 shell 里 export，工具版本由 `toolchain` 指纹记录。
- 评测脚本自己判断失败类别：候选写错（语法错误、结果不对）退出 1；工具缺失、超时、许可证退出 75。不要把编译器报错一律当环境故障。

## 4. 任务合同 `tasks/<task>/revisions/r0001/task.json`

研究任务需要跨 run 累计成果时，在 task 顶层设置可选 `results_path`，值为项目相对 Markdown 路径（例如 `research/results/task-a/README.md`）。已有成果优先复用原位置；跨 revision 沿用同一稳定入口，目录名不表示合同 revision。旧任务无此字段保持原行为。对已冻结合同启用入口时建新 revision，不回写旧合同或重置预算。通过 `results --initialize` 建最小入口，在人工区域链接现有 specs、批次计划和 evidence-index。没有 specs 时在 README 直接写结论与适用条件。

成果 README 由主流程维护，运行登记自动更新。只将确需 designer 修改的规格路径纳入 editable；不要把整个 research 或 .opc 放开。成果管理不要求数值 objective；实验有效性和推断质量可以作为验收条件，不能要求机制研究必须得到预期数字。

```json
{
  "task_id": "t-emu-tune",
  "revision": "r0001",
  "component": "emu",
  "goal": "在保证正确性的前提下最小化端到端延迟",
  "direction": "用户给出的探索方向，可以在 opc run --direction 覆盖",
  "requirements": [
    {"id": "REQ-001", "text": "结果与 golden 一致", "verification": "automated"},
    {"id": "REQ-002", "text": "延迟 ≤ 80000 周期", "verification": "automated",
     "check": {"metric": "latency_cycles", "op": "<=", "value": 80000}},
    {"id": "REQ-003", "text": "参数选择有可解释依据", "verification": "independent_review"}
  ],
  "acceptance": {
    "objective": {"metric": "latency_cycles", "direction": "minimize", "min_rel_gain": 0.01},
    "constraints": [
      {"metric": "correct", "op": "==", "value": 1},
      {"metric": "area_mm2", "op": "<=", "value": 4.0},
      {"metric": "energy_nj", "op": "<=", "relative_to_champion": 1.05}
    ],
    "target": {"metric": "latency_cycles", "op": "<=", "value": 80000},
    "repeats": 1,
    "noise_k": 2.0
  },
  "budget": {"max_attempts": null, "max_wall_seconds": 7200, "max_tokens": null,
             "max_stagnation": 8, "max_consecutive_infra": 3},
  "workers": {
    "expert": {"kind": "codex", "timeout_s": null},
    "designer": {"kind": "codex", "timeout_s": null}
  },
  "base_ref": "HEAD"
}
```

- `requirements[].check` 可选：`promote` 时据此判定该需求 met / not_met；没有 `check` 的需求须以 `gates: [门ID]` 声明覆盖或以独立 review 验证；缺覆盖不能自动通过。
- 指标缺失 = 拒绝（不是通过）。`target` 达到是专家进展信号，不强制停止；报告单列 `target_met`，完成仍由终验判断。
- 数字有噪声时设 `repeats>1`：收益必须超过 `noise_k × 重复测量的极差`。
- 自定义规则：`"rule": ".opc/eval/accept.py:accept"`（函数 `accept(old, new, **rule_params) -> (bool, str)`，必须在 `evaluator_files` 里）。
- worker 三选一：
  - `codex`：专家只读提出实验，设计者在隔离工作区改代码；token/时间上限默认不设置。
  - `dsh`：同一套角色分工，底层换成 DeepSeek Harness 的 headless 一次性运行
    （`dsh --profile headless --json`）；同样token/时间上限默认不设置。可选字段
    `binary`（默认 `dsh`，或环境变量 `OPC_DSH_BIN`）、`profile`（默认 `headless`）、
    `dsh_home`（默认为环境变量 `OPC_DSH_HOME`）、`extra_args`、`env`、`timeout_s`。
    三点差异：headless 没有 `--output-schema`，计划 JSON 由适配器从回复里解析，
    仍需通过 `validate_plan`；沙箱用环境变量 `DSH_PERMISSION_MODE` 选择
    （专家 `read-only`、设计者 `workspace-write`），越界写入失败关闭而不是询问；
    账号类失败（`MISSING_CREDENTIAL`、`QUOTA`、`RATE_LIMIT` 等）判 INFRA，
    不消耗搜索次数。专家回复 `NO_EXPERIMENT` 表示搜索枯竭。
  - `scripted`：固定搜索策略，不调用模型。参数类任务直接用
    `{"kind": "scripted", "strategy": "builtin:param_search", "options": {"file": "configs/emulator.json", "space": {"banks": [4, 8, 16]}}}`。

### 独立的 worker 环境配置

`opc init --apply` 自动生成 `.opc/local/workers.json`，该目录已由 `.opc/.gitignore`
排除。模型与 token/时间上限统一在此配置；只在用户明确指定相应上限时修改 budget，默认 token 无上限、Task 时间额度 7200 秒：

```json
{
  "budget": {"max_tokens": null, "max_wall_seconds": 7200},
  "expert": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
  "designer": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
  "reviewer": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
  "onboard": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"}
}
```

以上是新项目生成的 Codex 默认配置；已有本机配置不会被自动覆盖。
模型需当前账号和后端支持；推理强度也是后端和模型决定的，ArcHa 不把它固定成某个枚举。
角色字段的 null 表示继承。预算默认 max_tokens=null、max_wall_seconds=7200，max_attempts 缺失或 null 表示无轮数限制；已有明确上限保留，null 不能撤销。预算按 Task 汇总准备及所有 revision、Run 的原始 charges；准备使用 ledger 内的 Task scope，不创建执行 Run。onboard 的显式预算参数记录授权变更，追加总额度不清零消耗。历史 Run 的执行配置保持冻结。仅启用 token 或金额上限时要求相应用量完整；缺省 token 无上限时保留 unknown，不阻塞。默认模型调用 timeout_s=null，评价器 gate 工具超时独立保留。
文件缺失时保持兼容，JSON 格式、角色或字段拼写错误会报错，不会静默忽略。
旧项目可从 ArcHa 源码的 `opc/scaffold/workers.json` 复制到项目的 `.opc/local/workers.json`。
只有 runtime 的项目也可先创建该文件，再执行 onboard；初始化会保留已有配置。

优先级为：本机角色配置的非 null 值 > 该角色的合同字段 > 后端默认配置。
expert、designer 的 `kind`、超时、binary、profile 等仍由任务合同决定，
合同里的 `reasoning_effort` 也可直接使用。Codex 通过 `-m` 和
`-c model_reasoning_effort=...` 接收设置；显式的模型与强度优先于旧 `extra_args` 中对应参数。
仅配置模型或强度时，另一个设置继续继承合同或 CLI 默认值。

reviewer 仅在 `promote --review codex` 或 `--review dsh` 时运行，配置文件不会自动开启审核；
它使用独立的 reviewer 配置和后端默认值，**不再复用 expert 的任何选项**。
自定义 reviewer 程序入口请使用 `OPC_CODEX_BIN` / `OPC_DSH_BIN`；DSH 还支持 `OPC_DSH_HOME`。
onboard 的后端仍由 `--agent codex|dsh` 选择，模型与强度读取 onboard 项。
环境配置在执行 worker 的命令开始时读取，运行中的进程不热更新；修改后可在下一次命令（含恢复运行）生效，
不改变任务摘要，也不要求为模型切换创建新 revision。每次实际调用的 `*-request.json`
保留启动 argv；未显式配置时后端采用的默认模型和强度仍需查后端日志。

DSH 的 headless 没有模型 CLI 开关。切换到 DSH 时，请把相应角色的 Codex 默认项改成
`{}` 以继承 DSH profile，或同时提供 DSH 的 `provider` 和 `model`：

```json
{
  "expert": {
    "provider": "deepseek-official",
    "model": "<该提供方的模型ID>",
    "reasoning_effort": "high"
  }
}
```

ArcHa 在本次调用的日志目录写出 `*-model.patch.json`，通过 DSH 的 `--patch`
覆盖 `agent-default-model`，不修改全局 profile。覆盖时缺 provider/model 会直接报错；
不覆盖时仍沿用已有 profile。`provider` 字段只适用于 DSH；Codex 的提供方由其 CLI 配置管理。
`scripted` 不调用模型，不使用这些模型设置。onboard 将环境配置文件列为受保护输入，
起草 worker 不应改写它；文件中不要存放密钥。

## 5. 走一遍

```bash
# 合同审阅通过且明确决定进入执行准备后，将 execution_enabled 改为 true
opc check     -p <project> --task <task>     # 只校验合同，不运行
git add .opc && git commit -m "opc: onboard"  # 评价器和 .opc 必须已提交
opc preflight -p <project> --task <task>     # 在基线上跑全部门，报告指标与缺项
opc run       -p <project> --task <task> --direction "优先探索…"
opc status    -p <project> --task <task>     # 另一个终端；opc pause / opc stop 控制
opc promote   -p <project> --task <task> --confirm 3   # 晋升审核；--apply <branch> 才会动分支
```

起草阶段保持 execution_enabled=false；此时 check 会报告执行未启用，不代表需要立即打开开关。

运行结束时 `state` 为 `closed`（`target_met / best_within_budget / no_valid_candidate`）、
`paused`（可 `opc run` 继续）或 `blocked`（环境/worker 不可用，修好后 `opc run` 继续）。

## 6. 给 agent 的额外约束（opc onboard）

- 只在 `.opc/` 下创建或修改文件；不改项目源码、测试或已有配置。
- `.opc/runtime/`、`.opc/archa.py` 和 `.opc/research/` 是只读输入。起草只修改合同、评价器、context 和 Open items；工具事后检测输入变化，检测不等于文件系统隔离。
- 有 task-brief 时按第 7 节复用调查；没有时从 README、构建脚本和测试定位已有流程。读到足以确定范围、真实命令、指标、退出码及生成物即可起草，缺口再定向补读。
- 以本指南和已有合同模板作为接入接口；补读前先明确尚未解决的合同问题，再定位相关符号或段落。独立文件可批量读取，搜索结果只展开相关定义，已在提示词或工具结果中的内容直接复用。worker 沿用已有配置。
- 在 Windows 上创建供沙箱 worker 使用的验证副本或测试夹具时，在 `.opc/local/` 下用普通 `mkdir` 创建唯一目录以继承项目 ACL。Python 3.13+ 的 `TemporaryDirectory` / `mkdtemp` 使用私有 mode 0700，可能使沙箱身份无法访问；保留首次权限失败与修复后的验证记录，不以跳过验证代替修复。
- 没有把握的字段写 `TODO` 并在 `.opc/README.md` 列出缺项，不要编造指标名或阈值。
- 指标名必须是 `evaluate.py` 真实写出的键。
- 起草完成后运行 `check`。新适配层在 `.opc/local/` 副本中通过合同门验证一次合法测量（可调用 `CommandDomain(component).evaluate(...)`），再针对性验证候选失败及缺失/陈旧报告处理；直接调用适配器不能代替合同门接入验证。正式基线测量由后续 `preflight` 负责，起草保持执行关闭。
- 验证覆盖上述接入与测量语义即止，合同、context、Open items 齐备后简述产物与剩余阻塞并结束。输入变更检查复用 onboard 自带检查；框架内部审计和不影响起草的环境告警留给对应维护任务。


## 7. 来自两阶段讨论的任务简报

`opc onboard --brief <项目相对路径>` 会先检查 task-brief 的结构与源 map，再把完整正文及 SHA-256 来源信息交给起草 worker。不传此参数保留原有起草方式。`opc brief-check` 可单独运行，不调用模型。

地图技能只部署 runtime 和入口，不提前创建合同。对这类项目，onboard 在简报检查通过后补建关闭执行的合同骨架，再调用 worker；已有项目保留原合同。

简报只给目标范围、交付物和候选验收条件；基线、可改/冻结路径、预算、worker 和自主权边界由起草时根据仓库实际情况确定。先用提示词中的完整简报和它索引的相关 evidence，区分已定决定、建议和未知；源 map 只补读本任务的范围与依赖。复用已有调查结论和来源定位，核对影响合同的关键源码；证据缺失、冲突或与当前源码不符时再扩读。简报的 Open decisions 是起草时要处理或保留的事项，无需上游另做调查或补写交接材料。

- 字段映射：`Goal:` → `task.goal`，`Direction:` → `task.direction`，`- R*:` → `task.requirements[]`（`verification` 原样保留），`Objective:` → `acceptance.objective`。`Objective: none` 映射 acceptance.objective=null，不是阻塞项；`evaluator=待建/未知` 是由 agent 推进的 pending 准备待办；仅确认不可自主解决的外部条件才 external_blocked。`Done when` 和交付物 `D*` 写入 `.opc/context/REQUIREMENTS.md`。
- 把本任务在 map/简报中的相关背景、方向、完成标准、约束、已有能力写入 `.opc/context/` 的精简材料，并用 `context_files` 选择这些 Markdown 文件；未选择时使用 PROJECT、REQUIREMENTS、DECISIONS 三份材料。专家在只有研究材料的目录运行，不读取源码或其他 `context_files`，每份材料最多读取前 20000 字符。designer 负责读代码、定位文件和实现。
- 每个验收 gate 写明真实命令/评价器是否存在。缺失的实现、用户未定的预算、无法表达的研究语义都作为 blocking Open items 写入 `.opc/README.md`，保持 `execution_enabled=false`；不要用模板默认数或虚构优化分数代替。
- 只有内容与 `opc.scaffold.task_template(task_id, component_id)` 完全一致的 revision 才是可直接填写的空模板。部分填写、仍含 TODO 的合同也不是空模板。已有真实内容的 revision 保留：不同研究任务创建独立 task；同一任务的合同变更创建新 revision，并记录对应简报。
- 无源码补丁的测量可复用冻结评价命令，强制新测量；未执行、缓存结果、测量失败分别如实记录。额外诊断需由现有门输出结构化数据，不扩建通用实验调度。每轮独立研究审核、多任务依赖调度不在当前流程内。

简报就绪仅指可以起草；`brief-check`、`check` 和 `preflight` 都不判断研究结论是否成立。

## 完成条件与直接任务

明确任务可省略地图，在 brief Source 使用 `Task: TASK.md` 指向真实任务来源；有地图仍使用 Map。复用已确认 brief 与调查，只核对关键合同依据。
无数值目标用 `acceptance.objective: null` 或省略 objective；不可造 0/1 进度分数。
requirements 的 check 指向真实指标；需求可用 gates: [冻结门ID] 声明覆盖；无 check 或门覆盖的需求应声明 review 并由终验审阅，不能自动视为已覆盖。
preflight 中可执行评价的功能失败是未完成基线，工具/输入/输出契约故障仍阻塞。
普通开发默认连续积累已保存工作版本，由 designer 局部测试；expert 可用 evaluate=true 请求正式评价。
base_attempt 同样用于停止时的交付选版。run 停止不代表完成，promote 对选定版本执行完整验收与必要 review；apply 仍显式。

## 授权范围内的准备

onboard --prepare 在同一预算内完成必要的 .opc 评价器接入和与改动相应的关键检查，保留必要有界探针回执；仅合同 preparation_review=true 时独立审核，当前任务相关摘要冻结在原 ledger。它永不启动正式实验。pending 由 agent 继续；external_blocked 须有实际失败证据；ready 仍需提交冻结文件和 check/preflight。正式执行继承准备消耗，不重置额度。prior-tokens 是已可靠计量的主流程/外部嵌套累计量（包含 cached input），不含命令已记录的 worker/reviewer；无上限时未知用量记录为 unknown 并继续，显式 token 限额下未知用量才停止新增派发。已运行的合同只能新 revision/run，不原地改变验收。

每次交给正式 run 或终验 reviewer 前，主流程用相同 onboard 参数加 `--record-usage` 更新最新累计主流程/外部嵌套 token 和耗时；此选项只记账、不调用 worker 或重复审阅，沿用已有冻结回执。无 token/时间上限时可省略累计主流程用量并保留 unknown；相应显式上限才要求可靠累计量。

### 8.1 Codex 状态目录只读与用量对账恢复

Codex CLI 的状态目录与 `-s workspace-write` 的项目写权限是两层约束。
CLI 继承 `CODEX_HOME`（默认 `~/.codex`）；外层沙箱将该目录设为只读时，
内层 sandbox 参数不能授予写权限。ArcHa 不自动提权，也不复制认证文件或替换用户配置。
可在已授权可写的环境运行，或把 `OPC_CODEX_HOME` 指向**已配置好认证、模型和指令的现有绝对路径**。
也可以在 `.opc/local/workers.json` 的 `onboard`、`reviewer` 等角色中设置 `codex_home`；
优先级为角色配置、`OPC_CODEX_HOME`、继承的 `CODEX_HOME`。准备与审阅两个角色都应配置。
该目录必须在外层环境可写；不要仅创建空目录而遗漏所需配置。

启动失败不会自动证明模型用量为零。仅操作系统未能创建子进程的情况可确定没有模型派发；
CLI 已启动但没有完整 usage 回执时保留 unknown 与原始 worker_error；只有显式 token 上限才因缺少 token 计量停止后续派发。
每次准备使用独立的 `.opc/local/onboard/<call-directory>/`，保留对账所需的旧日志。

若已有 `accounting_unknown`，沿用原 task、预算和最新累计 host usage 调用 onboard，
返回的 `unresolved_accounting` 列出待对账事件的 `seq`。账本历史事件不得删除。
核实实际调用记录后，在项目内保存证据与 JSON 对账文件，例如：

```json
{
  "entries": [
    {
      "event_seq": 42,
      "additional_tokens": 120,
      "additional_wall_seconds": 0,
      "evidence": ".opc/local/usage-evidence.json",
      "reason": "actual total 200 tokens minus 80 already charged; elapsed time already charged"
    }
  ]
}
```

`additional_*` 是扣除已入账部分后需要**补记的差额**，包括遗漏的嵌套调用；不是调用总量，
也不能重复包含 `--prior-tokens` / `--prior-wall-seconds` 中的 host 用量。
零差额必须有证据说明原账目已完整。旧事件缺少 call_id 时，需要人工通过旧日志建立对应关系；
无法确定实际用量时保留 unknown，显式 token 上限下继续保持阻断，不能用估算填零。

在原 onboard 命令上增加 `--reconcile-usage .opc/local/reconciliation.json`。
该命令只对账，不派发 worker：它验证事件归属、非负有限用量和项目内证据文件，
原子追加补记费用与带证据 SHA-256 的 `accounting_reconciled` 事件。
相同回执重复提交不重复扣账，冲突回执被拒绝；没有对账的其他事件继续阻断。
证据内容的真实性与差额计算由提交者负责，文件存在与哈希校验不等于自动认证用量。

全部对账后状态转为 `pending`（尚未 ready 时 CLI 返回非零），预算耗尽则仍为 `budget_exhausted`。
随后移除 `--reconcile-usage` 再执行原 onboard 命令，重新完成准备与独立审阅。
对账不会重置预算，不会授权正式实验，也不会自动恢复历史 ready 回执。即使最后一条准备回执仍是旧 ready，只要本次解除过未对账事件，也必须退回 pending，重新准备和独立审阅。
`--record-usage` 仍仅更新 host 累计用量，不能代替某次调用的对账。

本修复随 ArcHa 源码发布；项目内已有 `.opc/runtime/` 快照需要通过正常运行时代码更新流程同步，
不会因更新源仓库而自动生效。

Codex 状态目录语义参考：[OpenAI environment variables](https://learn.chatgpt.com/docs/config-file/environment-variables)。


准备默认仅执行与本次接入改动对应的必要检查，不固定建设全套负控或通用监控工具。ready 表示必要接入完成，不代表研究结论成立。合同显式设置 `preparation_review: true` 时保留独立准备审核；旧 ready 回执继续有效。冻结仅覆盖当前 task、component 及 evaluator_files（显式共享依赖也在这些 glob 中登记）。

默认按用户任务与证据自主形成简报及合同，不为大纲确认、缺省预算或缺省计量停下来提问。默认时间额度两小时，只有用户明确授权时修改总额度；onboard 的 --max-tokens / --max-wall-seconds 是显式上限入口并写回该文件，未传时读取现有配置。未知主流程用量记录为 host_usage_unknown，不假报已完整计量。

## 目录式技能交接

archa-task/archa-loop 接受具体任务目录，内部 CLI 继续使用 --brief 文件参数。准备时显式传入按简报路径绑定的 --task；相同目录摘要变化保留 task ID，按已有 revision 规则处理。不同专题的 R01 不代表同一执行任务。worker 必须以提示中的 Target task ID 为目标，缺少时创建其合同，不修改其他任务。交接在 DECISIONS.md 追加 brief 项目相对路径、SHA-256、实际 task ID、revision 与合同路径；索引不参与路由。旧式交接核对后补记，不改旧 ID。
