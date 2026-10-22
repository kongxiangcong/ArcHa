# OPC 项目接入与目录规范

版本：v0.2，2026-10-22。补充[框架实现方案](OPC%20框架实现方案.md)，约定项目接入、每次实验的存放位置与生命周期。本轮已实现接入骨架/路径规划工具和合同校验；完整派发、冻结、隔离、对账服务仍待实施。

## 1. 核心判断

**OPC 是项目外的通用工作流运行时；目标项目保留原目录，只增加 `.opc/` 接入层。**接入任何项目指协议可以适配，不代表一个目录天然具备可自动优化的参考、评价器和资源。

从 openTPU 借用四种资产分开管理的方法：组件配置、候选工作区、实验原件、构建缓存。其 `tools/tourney/components/`、`.tourney/`、`tools/tourney/runs/`、`build/` 分工有源码依据，但它的 RTL 字段、秒级 slot 命名和强制清理不是通用规范。[固定版本核查](docs/research/project-integration.md)

从 gsd-core 借用项目盘点、稳定需求 ID、上下文决策和需求到验证追踪。它既有模板，也有确定性检查；不过自报覆盖不能代替 reviewer 身份和原始实验。OPC 不安装第二个 Master，不复制整套模板树。[GSD 固定版本核查](docs/research/gsd-contracts.md)

减法：不搬迁源码、不为每个项目复制一份 OPC 引擎、不把运行原件默认提交 Git、不把每轮实验变成一轮人工表格填写。项目只提供领域适配信息，Ge 完成结构化转换并管理缺项。

## 2. 三个根目录与一个权威状态库

| 根目录 | 内容 | 默认 / 迁移规则 |
| --- | --- | --- |
| `project_root` | 用户源码、已有文档、测试、`.opc` 小型接入资产 | 保留原结构；从显式项目路径解析，不能依赖当前 shell cwd |
| `artifact_root` | 输入快照、每次实验原件、冻结提交、审核、可重建视图 | 默认 `<project>/.opc/local/artifacts`；可映射项目外磁盘或受控对象存储 |
| `workspace_root` | 设计/审核的独立工作区与可丢弃构建文件 | **必须显式指定项目外目录**；不在原 checkout 内实验，不让 worktree 嵌套到源码树 |

本机运行时默认 `.opc/local/ledger.sqlite3` 是该项目任务、接纳、预算和 job 的唯一权威；Ge 的跨项目 registry 仅保存项目 ID→控制端点/本机绑定。未来将权威迁移到服务数据库时，本地只做只读投影，不保留第二个可写接纳库。路径工具当前不会创建 ledger 或执行这些服务。

`project_id` 是稳定身份，不取决于文件夹名；搬目录不改它。task 在项目内唯一；run 使用服务生成的 UUID/ULID 或等价唯一 ID；attempt 序号由该 run 的事务账本单调分配。演示 CLI 允许手填 ID，仅用于路径预览，不保证多控制器并发分配。

## 3. 目标项目增加什么

```text
<target-project>/
  src/ | rtl/ | compiler/ | sim/ ...       # 原项目，无强制名称
  tests/ docs/ README.md AGENTS.md ...    # 原项目，保留
  .opc/
    .gitignore                          # 忽略 local/，不改根.gitignore
    project.json                        # ProjectConfig，稳定身份与协议/adapter版本
    README.md                           # 项目接入说明与当前缺项
    components/
      <component-id>.json               # ComponentConfig：范围、冻结路径、工具argv
    context/
      PROJECT.md                        # 原项目价值、已有能力、边界与来源
      REQUIREMENTS.md                   # 稳定REQ-ID、当前→目标→验收
      DECISIONS.md                      # 项目级已定决定及其来源
    tasks/
      <task-id>/
        revisions/r0001/
          task.json                     # TaskSpecV02，冻结版本
          TASK.md                       # 对该JSON的可读说明
          CONTEXT.md                    # 锁定/自主/延期事项与canonical_refs
    exports/                            # 可选：显式导出的审后报告和证据索引
    local/                              # 不入Git；host绑定、运行状态和缓存
      bindings.json                     # 本机绝对路径映射；不放明文secret
      ledger.sqlite3                    # 本机模式唯一权威（未来服务实现）
      controller/logs/                  # 服务日志，不是实验唯一原件
      cache/                            # 可重建，按完整输入指纹分区
      artifacts/                        # artifact_root的默认位置
```

按需创建：init 只生成 project.json、三份小型上下文骨架、组件/任务说明；**不会生成任务、ledger、实验记录或已验收结果**。`execution_enabled=false`、`adapter_id=unconfigured`。完成组件配置不等于工具环境已经验收；preflight 仍需运行且保存回执。

`.opc` 配置可进入 Git，但创建文件不意味着授权 stage/commit/push。raw logs、模型轨迹、数据、凭证和机器绝对路径不默认入 Git。现有 `.planning/`、`AGENTS.md`、CI、Makefile 等只读导入为带版本来源；不覆盖、不同时维护两套可写任务完成状态。

## 4. 每次实验产物的准确位置

以下 `A = <artifact_root>/<project_id>/<task_id>/<run_id>`。所有子路径都相对 A，项目名字相同也通过 ID 隔离。

```text
A/
  run.json                              # 服务创建的run身份、task版本/摘要
  frozen/
    task.json                           # 本次run使用的TaskSpec原件
    baseline-manifest.json              # 干净commit或明确的源码快照
    project-config.json component.json  # 接入配置版本快照
    inputs/ evaluator/ environment/     # 小型原件；大输入为可取回的hash引用
  attempts/
    a000001/
      plan.json                         # 专家本轮ExperimentPlan
      PLAN.md                           # 由计划生成的可读解释
      candidate/
        source/                         # 在授权范围保存实际候选文件
        source-manifest.json            # 路径、hash、大小、来源基线
        changes.patch                   # 辅助审查，不能代替完整快照
      experiment/
        jobs/<job-id>/
          request.json                  # argv、cwd、env白名单、输入摘要、幂等键
          stdout.txt stderr.txt         # 原始输出，非摘要
          receipt.json                  # exit/status、真实job身份、时间、费用事实
          metrics.json                  # 单位/聚合/计量窗口/证据等级
          outputs/                      # 仿真波形、编译产物、trace、综合报告等
      submissions/<submission-id>/
        submission.json                 # 生产者主张、coverage、偏离与未知
        manifest.json                   # 引用本次冻结原件，服务重算
        SUMMARY.md                      # 可读总结，不自行签署通过
      reviews/<review-id>/
        request.json                    # 固定submission/hash与reviewer调用
        Standards.json Spec.json        # 两轴原始判断/证据
        decision.json                   # ReviewDecisionV02
        VERIFICATION.md                 # gap、未测行为和条件结论
        jobs/<job-id>/...               # 独立复算日志/回执，独立身份
  views/
    STATE.md HANDOFF.md                  # ledger投影，带event cursor
    report.json                         # 汇总视图，不是权威
```

工作区另放：

```text
<workspace_root>/<project_id>/<task_id>/<run_id>/a000001/
  designer/                             # 基线展开/独立worktree，候选可改范围
  reviewer/                             # 独立复算scratch，只读挂载已冻结提交
```

对应关系：一次 attempt 可以有多个实验 job、多个冻结 submission 和多个 reviewer 回执；不能把“一轮”“一次工具命令”“一次提交”“一次审核”当同一个计数。`a000001` 只有在 run 作用域内唯一，禁止只用当前时间或组件名做完整路径。

同一失败实验的重试生成新 job ID，并关联原 job；只重试审核时继续绑定原 submission，生成新 review ID，不复制为新的实验。修改任何代码、输入、主张或指标口径都形成新 submission；需要新实验时增加 attempt，预算不归零。未知 job 恢复不创建新 ID掩盖重复执行。

文件写入先使用临时文件与原子发布；服务接纳后是逻辑不可变对象。生产权限/对象存储需禁止作者篡改；本轮骨架工具只验证路径，不提供该权限保证。

## 5. 可迁移引用与本机绑定

共享合同存逻辑 URI，不保存 `D:\...` 或用户 home：

```text
project://<project-id>/rtl/mxu.sv
artifact://<project-id>/<task-id>/<run-id>/attempts/a000001/submissions/<submission-id>/manifest.json
```

`project://` 需要同时绑定 Baseline 和文件 hash，不能解释成“永远读取当前 checkout”。`artifact://` 由 project 的已登记 artifact store 解析；URI+内容hash+大小+生产job共同形成引用。迁移对象存储只更换本机/服务绑定，旧合同无需改路径。

本机 `.opc/local/bindings.json` 示例（字段为设计约定，工具不自动配置远端）：

```json
{
  "project_id": "p-example",
  "project_root": "D:/work/my-project",
  "artifacts": "D:/opc-artifacts",
  "workspaces": "D:/opc-workspaces",
  "controller": "local-single-writer"
}
```

artifact_root 默认在专用local子树；外置时必须位于项目外，且与workspace_root不能重叠。解析后检查绝对路径、盘符、符号链接/junction、`..`、Windows设备名与大小写别名；不能只用字符串 startswith 判断目录包含关系。服务写入前仍需检查权限和竞态。路径工具的符号链接反例在本机权限下跳过，不能宣称已完成全部平台路径隔离验收。

## 6. 怎样接入一个已有项目

| 步骤 | Ge/工具做什么 | 不满足时 |
| --- | --- | --- |
| 1 发现 | 用户给项目路径；确认真实根、已有.opc/.planning/规范、Git与dirty状态 | 已有.opc走read/import，不重新初始化 |
| 2 盘点 | 读源码入口、模块、测试、参考、构建命令与已有证据；记录当前能力 | 代码存在只记observed，未经验证不写accepted |
| 3 登记 | 建ProjectConfig、组件草案、源文档引用；保留默认disabled | 缺路径/adapter/资源列缺项 |
| 4 基线 | 选具体commit，或按明确清单制作源码快照并记录dirty/untracked | 不reset/stash/clean；不静默忽略用户修改 |
| 5 适配 | 映射领域commands、指标、oracle、允许/冻结路径和输入 | 缺evaluator先生成建设任务，不立即竞赛 |
| 6 Preflight | 检查工具/资源、路径权限、输入可取回、基线正确性/可计量性 | 保存失败原件，返回具体缺项，不假装ready |
| 7 Smoke | 有限预算下完整经历计划→实现→实验→独立审核→接纳/拒绝 | 未完成的环节保持pending/blocked |
| 8 启用 | 验证停止、恢复、只重审、内容失效；再启自动多轮 | Ge继续展示真实就绪状态 |

运行前要求满足什么取决于任务类型：纯机制调查可以接受尚不知道答案；优化任务必须有冻结评价器与可比较基线。非Git项目也能接入，但隔离方式为带manifest的源码复制/快照，而不是假造commit。新项目先做“搭建最小参考/测试入口”的任务。

脏工作区有两条明确路线：只使用用户指定的已提交版本，说明不含未提交修改；或在授权范围复制已跟踪修改和显式允许的untracked文件，生成完整快照。禁止把 `git diff` 视为全量输入，禁止默认采集secret、大数据或任意忽略文件。任何后续worktree都从记录的baseline创建，不从仓库默认分支猜测。

## 7. 实际可用的接入辅助命令

当前目录是框架工作目录，以下命令从这里调用，`--project-root` 指向目标项目：

```powershell
# 默认只读预览：不创建.opc、不执行测试或agent
python tools/project_layout.py init --project-root D:/work/my-project --project-id p-example --name MyProject

# 显式写入接入骨架；已有.opc立即拒绝覆盖
python tools/project_layout.py init --project-root D:/work/my-project --project-id p-example --name MyProject --apply

# 只计算本次实验路径，实际生产ID应由服务分配
python tools/project_layout.py paths --project-root D:/work/my-project --project-id p-example --task-id t-gemv --run-id r-example-001 --attempt 1 --workspace-root D:/opc-workspaces
```

这是已实现的CLI，不是尚不存在的 `opc start`。它不会安装GSD、启动模型、运行项目命令、建立Git worktree、创建ledger或接纳结果。两种目录完全不同的 fixture（`src/` 编译项目和 `rtl/` 硬件项目）已实际接入，源码hash保持不变，见[运行示例与证据](examples/project-onboarding/README.md)。

组件配置例子由schema约束，实际命令仅是数据；adapter将命令ID映射到已登记执行器。生产预检必须识别 `shell -c` 等绕过，不能把“argv数组”误认为安全执行边界。领域代码改动许可是项目级限制与TaskSpec限制的交集；`.opc`、`.git`、evaluator、golden、验收输入默认排除。glob可能覆盖冻结路径时，拒绝优先。

## 8. 不同项目怎样复用同一框架

| 项目类型 | 保留的目录 | 领域adapter关注 | 原件示例 |
| --- | --- | --- | --- |
| 编译器 | `compiler/` 或已有 `src/` | IR/数值语义、pass选项、编译→执行连接 | IR前后快照、编译日志、执行trace与差异 |
| 模拟器 | `sim/`、既有输入目录 | 事件/请求顺序、时钟、确定性种子、参考对齐 | 配置、请求trace、统计窗口、对照结果 |
| RTL/openTPU | `rtl/`、`boards/`、`tools/` | bit-exact、约束、综合/P&R/板卡资源 | RTL快照、波形、formal/综合/时序原报告 |
| 软件服务 | 原有app/tests结构 | 接口、状态、副作用、集成测试 | 测试原件、接口调用记录、候选patch |
| 纯研究/新工程 | 原有文档和数据引用 | 来源、可证伪假设、证据覆盖 | source refs、探针、反例、条件结论 |

核心只认识合同、job、submission、review、budget，不硬编码“GEMV/RTL”。本轮GEMV示例还使用旧的demo目录，**不迁移旧原件以伪装已经接通v0.2**；新接入fixture验证的是目录与合同，不是领域功能。

## 9. 保存、归档、清理与发布

- 每个失败、超时、取消都保存已获得原件、退出/取消状态与缺失清单；不能用空文件补齐不存在的证据。
- 冻结原件并验证hash/可取回性后，工作区才有资格被清理；未知活job、未结预算或被pin的review对象禁止清理。
- 本地artifact目录虽被Git忽略，仍是审计资产，需要备份；ignored不等于可删除。外置迁移需核对对象hash与引用完整，再切换alias。
- cache可重建，key需包含实际源码、输入、evaluator、工具版本、参数与环境；被引用的报告先复制/固化进artifact store。清cache不删除审计对象。
- 生成新版本HANDOFF/summary保留历史；当前视图可重建，不手工改accepted。job与receipt不因为换会话删除。
- 选为champion、合同接纳、合并/发布分别记录。发布仍需要既有或新增的明确授权；模板不能自动获得git提交与部署权限。

本轮没有实现GC、远端存储迁移或自动worktree清理。其安全条件作为后续运行服务验收，不直接复用openTPU的force cleanup。

## 10. 与合同v0.2的关系

[合同升级说明](contracts/V0.2.md)把项目身份、基线、需求追踪、关键连接和逐项证据纳入结构。项目级Project/Requirements/Decisions负责语义上下文；TaskSpec/Plan/Submission/Review的JSON负责版本化机器交接；STATE/HANDOFF/SUMMARY是有来源的视图。

主链为 `ProjectConfig → ComponentConfig → TaskSpec → ExperimentPlan → Job → Submission → ReviewDecision`。**已有v0.1与GEMV历史不原地升级**。先运行迁移检查、填写来源和REQ映射，创建新的v0.2任务版本及新审核，才能进入新工作流。
