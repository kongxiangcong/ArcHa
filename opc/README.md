# opc：专题研究引擎

安装及工作台启动见 [仓库入口](../README.md)。本地部署入口 `python PROJECT/.archa/archa.py` 与安装后的 `opc` 使用同一 CLI。

所有命令都要求 `-p PROJECT --topic SLUG`：

| 命令 | 行为 |
| --- | --- |
| `init [--goal TEXT 或 --goal-file PATH] [--max-rounds N] [--template default或pim]` | 初始化专题，不覆盖已有目标、状态或配置；空目标不能运行 |
| `check` | 只读校验 Worker 配置 |
| `step` | 执行一次 Expert、Executor 或收尾调用 |
| `run [--debug-probes / --no-debug-probes]` | 执行到领域终态、探针断点或调用失败 |
| `stop` | 停止当前调用并等待归属进程结束 |
| `revise --feedback "方向意见"` | 在调试断点由 Expert 重拟当前探针，保持轮次和预算；失败保留正式提案 |
| `resume [--add-rounds N] [--debug-probes / --no-debug-probes]` | 恢复提交，显式解除已处理阻塞，按需追加预算并继续 |
| `status` | 只读查看状态、轮数、下一动作、当前执行和错误 |
| `report` | 从已有材料生成专题内 `PROGRESS_LOG.md`，不调用 Worker |

退出码：一般成功为 0，输入或执行错误为 2；`run`/`resume` 分别以 0、3、4、5 表示 `COMPLETED`、`IN_PROGRESS`、`BLOCKED`、`BUDGET_EXHAUSTED`。正常探针断点等待返回 0（专题仍为 `IN_PROGRESS`）。预算耗尽不是调用失败，也不表示目标已完成。

`--debug-probes` 在专家提交探针后、Executor 派发前正常结束并释放锁。设置保存在专题 `.debug-probes` 标记中；后续 `run`/`resume` 执行当前探针，到下一探针再次停下。首次启用时已有待执行探针也会先停下供检查。`--no-debug-probes` 显式恢复自动运行；`step` 仍只派发一次角色。`status` 的 `debug_probes` 表示选项，`probe_breakpoint` 表示无错误且空闲的探针等待。

工程 `.archa/workers.json` 优先；缺省使用 [分发配置](scaffold/workers.json)，两个角色均为 Codex。例如自定义 Executor：

```json
{
  "expert": {"provider": "codex", "model": "gpt-6.1-sol", "reasoning_effort": "medium"},
  "executor": {
    "provider": "custom",
    "command": ["python", "investigate.py", "{output_file}"],
    "timeout_seconds": 300
  }
}
```

所有角色从 stdin 读取任务并自行写入协议文件；stdout/stderr 仅进入原始日志。非零退出、超时或空输出均不发布结果。命令不隐式经过 shell。

运行模块职责：`core/engine.py` 调度与预算，`core/workspace.py` 状态及成果发布，`core/topic_control.py` 工程执行身份与停止，`adapters/worker.py` 暂存产物与调用，`adapters/providers.py` 配置及命令构造，`adapters/prompts.py` 角色上下文，`log.py` 按需报告。OS 进程树与独占锁由 `core/platform.py` 和 `core/windows.py` 提供。

历史数据不迁移；旧契约、Run、账本、Reviewer、晋升、工具拦截及暂停接口已退役。研究完成不意味着独立审核通过、合并或发布。

## Worker 协议

配置直接包含 `expert`、`executor`；各角色必须指定 `provider`（`codex`、`dsh` 或 `custom`）。可选 `model`（空字符串表示 CLI 默认值）、`timeout_seconds`（默认 1800 秒，正的有限数值）、字符串映射 `env`。`reasoning_effort` 只适用于 Codex；`command` 只适用于 custom，必须是非空 argv 数组。未知字段、不支持的选项、错误类型与不可用变量直接报错。`check` 只校验配置，不调用模型，也不证明任务环境就绪。

| custom 命令模板变量 | 含义 |
| --- | --- |
| `{workdir}` | 目标工程目录，也是进程工作目录 |
| `{topic_dir}` | 专题目录 |
| `{prompt_file}` | 本次调用提示文件，调用结束清理；任务仍接入 stdin |
| `{output_file}` | Expert 临时探针、Executor 临时结果；收尾时为临时状态 |
| `{state_file}` | Expert 临时状态；Executor 读取的正式状态 |
| `{model}` | 必须明确配置非空模型；不使用此变量时无需填写 |

模板按 argv 元素渲染，不提供 shell 转义；字面大括号写作 `{{` 与 `}}`。显式调用 shell 时由配置者负责引用。所有 Provider 完整继承宿主环境并叠加 `env`，沿用本机 HOME、登录与工具链。Codex 使用无状态、非交互 `exec --ephemeral --json`，继承用户 CLI 权限配置；权限不足直接失败，不自动放宽重试。DSH 使用 `dsh --profile headless --json -`，指定模型时通过临时 `--patch` 加载原生 `internal/config` 钩子，仅覆盖 `agent-default-model` 的 model，保留本机 provider、reasoningEffort 与配置表达式；调用结束删除补丁及模块。DSH 0.2.2-rc.1 的普通补丁会替换整个 config，不能用仅含 model 的补丁模拟深合并；模型为空不传补丁，继承本机配置。仅选择 DSH 时才需要安装和配置它。DSH headless 默认使用 API-key 路由，不默认启用交互登录存储；请按本机 DSH 配置设置认证。引擎不复制 HOME、登录文件或 CLI 会话，也不自动改变认证及权限配置。后续轮次可直接切换 Provider，继续读取专题权威材料。不要将 Codex `-o` 指向协议文件，它会用最终聊天摘要覆盖文件。

Expert 写完整临时状态，继续探索时还写探针；完成或阻塞时不要求新探针。Worker 不删除调用方准备的状态草稿。输出只有在退出码零、未超时、必需内容非空且归属后代进程结束后才允许发布。创建、登记、等待和异常都在进程生命周期内；登记失败也收回已启动进程。stdout/stderr 直接写入同一原始日志，中断保留内容，不从日志回填产物。重试覆盖同轮同角色日志，重拟与收尾分别写 `.expert_revise.log`、`.expert_finalize.log`，不承诺完整调用审计。失败即停，无自动重试。

### Worker configuration migration

升级固定运行时不会覆盖已有工程配置或研究材料。旧配置在派发前拒绝；请手工编辑 `.archa/workers.json`：

1. 删除外层 `roles`，将 `expert`、`executor` 移至顶层。
2. 将 `preset: "codex"` 改为 `provider: "codex"`。自定义命令增加 `provider: "custom"`；`scripted` 预设已删除，确定性脚本按 custom 文件协议接入。
3. 删除 `input_mode`、`output_mode`；脚本从 stdin 读取正文，写入 `{output_file}`／`{state_file}`，不能仅打印结果。`{prompt_file}` 仍可作为路径参数。
4. 保留模型、超时和环境覆盖；`reasoning_effort` 仅保留在 Codex 角色。custom 仅支持上表变量，使用 `{model}` 时须提供非空模型。
5. 运行 `check` 验证配置，再按原专题的待执行动作继续。迁移不改写历史材料。

## 专题材料与状态约束

`.archa/topics/<topic>/` 中 `GOAL.md` 保存目标、范围、环境入口和完成判据；`STATE.md` 保存当前认知；`steps/step-01/` 起逐轮保存 `probe.md`、`result.md` 和角色日志。必要原件与脚本可以留存；`PROGRESS_LOG.md` 是按需衍生展示，不参与调度。模板由 [templates.py](scaffold/templates.py) 定义，默认领域中立，PIM 为可选模板。

状态文件以 `# Exploration State` 开头，紧随唯一的 `STATUS:` 和 `MAX_ROUNDS:` 元数据行，再以空行分隔正文。缺失、重复、非法头直接报错。预算为正整数，由引擎保留授权值，Expert 不能修改。认知正文按事实与边界、机制模型、条件化关闭分支、待解问题与阻塞、最近认知演进组织。

| 状态 | 含义及继续条件 |
| --- | --- |
| `IN_PROGRESS` | 目标未完成，按正式轮次文件派发；不表示进程正在运行 |
| `COMPLETED` | Expert 判断目标达成；只读返回，拒绝追加预算和重开 |
| `BLOCKED` | Expert 判断缺少条件且无可行替代；补齐条件后显式 `resume` |
| `BUDGET_EXHAUSTED` | 末轮已消化但目标未完成；显式追加授权轮数后继续 |

只有已提交 `result.md` 才计为完成一轮；只有日志或临时材料的步骤可复用。正式轮次须规范编号、连续，最多最后一轮有探针无结果；破坏结构的编辑直接报错。进程失败不自动写为 `BLOCKED`，否定结果仍是可吸收的证据。

先恢复提交，再推导下一动作：无轮次由 Expert 出题；有探针无结果由 Executor 执行；结果已提交且预算尚有余量由 Expert 消化并决定下一问；达到上限后只做收尾消化，不派发实验。普通 Expert 只提交 `IN_PROGRESS`、`COMPLETED` 或 `BLOCKED`；收尾先判断目标，达成则完成，否则为预算耗尽并保留阻塞条件。

追加预算在持锁下原子更新累计上限，保留历史用量；耗尽可转回 `IN_PROGRESS`，阻塞仍需显式恢复。预算检查先于派发，人工降低预算至已用量以下或无法覆盖待执行探针时报告具体错误并保留现场。

Expert 默认读取目标、当前状态与上一轮探针/结果；Executor 读取目标、状态与当前探针，历史按需读取，不注入全量日志。Expert 再读末轮结果时避免重复累加事实。选题、授权优化及工程改动保留边界见 [ADR](../docs/adr/0001-topic-workspace.md#讨论定锚与执行循环)，实际角色提示维护在 [prompts.py](adapters/prompts.py)。

## 独占、提交与恢复

同一工程（含不同专题）最多一个执行者。运行、单步、恢复、追加预算和恢复清理持有稳定 `.archa/.run.lock` 文件上的 OS 独占锁；文件存在不表示持锁，不能用 PID 检查替代锁，也不在持锁期间删除或替换锁文件。`status` 只读，不清理或派发。

当前执行描述记录专题、角色、轮次、时间、归属进程及停止状态，完整发布；它不是锁。引擎负责正常停止及清理，`stop` 与工作台只请求并等待归属进程树结束、恢复完成和锁释放。重复停止不影响后续新运行。崩溃恢复先取得独占权再处理可确认归属的残留进程；无法确认旧执行结束时明确报错并禁止派发，不按裸 PID 盲目终止进程。停止是中断当前调用，不是等本轮结束后暂停。

Expert 发布采用以下协议，保证进程中断恢复，不承诺机器掉电持久事务或工程副作用回滚：

1. Worker 向当前步骤的 `.staging.expert/` 写完整状态及需要的探针，正式文件不变。
2. 调用成功且输出检查通过后，引擎规范化状态头、保留授权预算；完成或阻塞时不发布探针。
3. 同文件系统原子重命名准备目录为 `.staging.commit/`，标记已验证、必须完成发布的提交。
4. 用 `os.replace` 依次移动状态及探针到正式位置；恢复继续移动提交目录中的剩余文件，空目录删除。两次文件替换不是跨文件瞬时原子操作，只读视图可显示“提交中”。
5. 仅有 `.staging.expert/` 时清理后可重试；有 `.staging.commit/` 时必须先完成发布，不能删除或重跑 Worker。提前完成、阻塞与收尾沿用此协议，仅发布状态。

Executor 写 `.staging.result.md`，成功检查后原子替换为 `result.md`。未发布调用可能重跑，已提交结果直接复用，不承诺外部实验恰好执行一次。清理恢复均在持锁且旧进程已结束后进行；临时材料不作为第二份认知账本，过期且无用途时清理。

人工修改须在正常停止并完成提交恢复后进行。普通恢复沿用待执行探针；明确纠偏的步骤以 [讨论技能](../skills/archa-discuss/SKILL.md) 为准。保留已完成轮次、状态头和授权预算；删除待执行探针不会撤销已提交认知或工程副作用，实质换题新建专题。报告要求无活跃执行或待发布提交，离线读取材料，不调用 Worker、不改变权威内容。

## 部署与观察边界

项目本地部署、固定运行时显式升级及配置保留见 [仓库入口](../README.md)。部署文件清单只维护在 [initialize.py](../skills/archa-discuss/scripts/initialize.py) 的 `RUNTIME_FILES`，安装器复用；包含传递依赖与模板资源。

工作台通过 L0 阅读摘录、L1 阅读原件；轮次材料抽屉内主动展开 L2「执行 Trace」，查看 Expert、Executor、重拟与收尾各自最近一次调用的生命周期和原始日志。运行或失败不会自动展开 Trace。每个角色的 `.events.jsonl` 与日志同轮存放，新调用原子替换事件流；旧记录不回填事件。Trace 是派生观测，`completed` 仅代表进程零退出，不代表研究产物提交；观测故障在命令诊断、原始日志与 L2 提示，不阻止合法产物提交。当前认知不冒充历史状态快照。控制提供停止、继续、追加预算和探针断点调试（HTTP `resume` 的可选布尔字段 `debug_probes`），请求与实际状态分开展示，服务端独占锁防止重复启动。HTTP `revise` 接收 `feedback` 字符串，共用 CLI 重拟控制；当前轮只保留最近一次 `feedback.md` 与重拟日志。主屏可提交方向意见并查看调整状态，直接读取当前探针，输入与认知状态、历史日志按需展开；专题详情的 `current_probe` 引用权威探针材料。材料读取限制在明确允许的根目录，禁止越界或执行原始 HTML；demo 使用同一专题接口。
