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
  "budget": {"max_attempts": 30, "max_wall_seconds": 14400, "max_tokens": 3000000,
             "max_stagnation": 8, "max_consecutive_infra": 3},
  "workers": {
    "expert": {"kind": "codex", "timeout_s": 900},
    "designer": {"kind": "codex", "timeout_s": 1800}
  },
  "base_ref": "HEAD"
}
```

- `requirements[].check` 可选：`promote` 时据此判定该需求 met / not_met；没有 `check` 的需求须以 `gates: [门ID]` 声明覆盖或以独立 review 验证；缺覆盖不能自动通过。
- 指标缺失 = 拒绝（不是通过）。`target` 达到是专家进展信号，不强制停止；报告单列 `target_met`，完成仍由终验判断。
- 数字有噪声时设 `repeats>1`：收益必须超过 `noise_k × 重复测量的极差`。
- 自定义规则：`"rule": ".opc/eval/accept.py:accept"`（函数 `accept(old, new, **rule_params) -> (bool, str)`，必须在 `evaluator_files` 里）。
- worker 三选一：
  - `codex`：专家只读提出实验，设计者在隔离工作区改代码；必须设 `max_tokens`。
  - `dsh`：同一套角色分工，底层换成 DeepSeek Harness 的 headless 一次性运行
    （`dsh --profile headless --json`）；同样必须设 `max_tokens`。可选字段
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
排除。四个角色分别配置模型和推理强度，不需要修改任务合同：

```json
{
  "expert": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
  "designer": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
  "reviewer": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
  "onboard": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"}
}
```

以上是新项目生成的 Codex 默认配置；已有本机配置不会被自动覆盖。
模型需当前账号和后端支持；推理强度也是后端和模型决定的，ArcHa 不把它固定成某个枚举。
将字段设为 `null` 表示继承；也可以省略字段或角色。
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

- 字段映射：`Goal:` → `task.goal`，`Direction:` → `task.direction`，`- R*:` → `task.requirements[]`（`verification` 原样保留），`Objective:` → `acceptance.objective`。`Objective: none` 映射 acceptance.objective=null，不是阻塞项；`evaluator=待建/未知` 等真实验收缺口写成 blocking Open item。`Done when` 和交付物 `D*` 写入 `.opc/context/REQUIREMENTS.md`。
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
