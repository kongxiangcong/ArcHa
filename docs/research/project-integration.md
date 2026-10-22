# 通用项目接入与实验目录：openTPU 源码核查

日期：2026-10-22。固定快照：`FeSens/openTPU@506e81b1d297e22739dab5ecaeee684493d5c720`。这是原交接使用的固定基线，本轮重新读取其源码；不声称它是最新版本。仅做静态核查，没有运行 openTPU、EDA、模型调用或修改其仓库。

## 1. 先区分可复用方法与仓库特定布局

openTPU 的 tournament 直接嵌在目标仓库 `tools/tourney/`，其配置知道 RTL、测试、板卡和构建工具。对 OPC 有价值的是四种文件的分离：**版本化接入配置、可丢弃候选工作区、持久实验与审核证据、可重建构建缓存**。通用框架不应要求所有项目先改成 openTPU 的 `rtl/boards/models/` 目录，也不应把每次实验的大量日志、模型与构建输出提交进 Git。

默认前提需要修正：“接入任何项目”表示同一协议可适配项目，不表示发现一个目录就能直接优化。每个项目仍需确定基线、允许修改范围、冻结评价器、工具/资源、指标及验收。缺少其中某项时先生成接入缺口或建设任务，而非随意猜测成功标准。

## 2. 已核实的 openTPU 目录与生命周期

| 数据 / 位置 | 源码事实 | 对 OPC 的启发与限制 |
| --- | --- | --- |
| `tools/tourney/components/<name>.yaml` | 包含 allowed、synth sources/params、target_mhz、fast/board tests、perf；`load_component()` 从固定目录加载 | 复用“项目能力清单 + 组件级配置”；通用合同不固定 RTL 字段 |
| `.tourney/<comp>/<slot>`、`.tourney/fmax-<comp>/<slot>`、`.tourney/unit-<comp>/<slot>` | 每个候选创建独立 Git worktree，基于 champion | 隔离候选源码；路径应增加稳定 project/run/attempt ID，不能仅用组件名 |
| `tourney/<comp>`、`tourney/fmax`、`tourney/unit/<comp>` | 保存当前 champion；胜者提交后用旧 SHA 做 CAS 更新 | 可保存“当前最佳”索引，但要区分候选接纳、选择为最佳、发布到主分支 |
| `tools/tourney/runs/<comp>/champion.json` | 按 SHA、backend、period 缓存基线指标 | 缓存 key 应覆盖实际读取输入、评价器、工具、配置；不能只按名字复用 |
| `.../agents/<slot>.<role>.jsonl` | 保存 hypothesis、implementation、scribe 的调用轨迹 | 原始会话与工具日志属于实验原件；可能含敏感内容，不默认进 Git |
| `.../patches/<slot>.patch` | sandbox 通过后，用 `git diff` 保存改动；之后 lint/test/synth 失败仍可保留 patch | 失败候选保留很有价值；但此路径不保证所有早期失败都有完整可重放快照 |
| `.../log.jsonl`、`LESSONS.md` | 每个 slot 记录结果、理由、假设、实现说明、各角色/门耗时、usage，并追加经验 | 事实记录与经验摘要分开；摘要不能替代原件，经验必须关联版本和适用条件 |
| `.../REPORT.md`、`progress.png` | report.py 从 log/champion 派生可读报告 | 报告是投影，不能反向成为接纳权威 |
| `build/tourney/<comp>/<slot>` | 本地综合/STA 输出；worktree 的 build 与 models 链到共享位置 | 缓存与大输入可外置；共享可写 cache 必须校验指纹，不能等同只读证据 |
| `tools/tourney/runs/_full/<key>-<MHz>.json` | 全设计结果共用缓存，key 由构建实际读取的 RTL/boards 内容与时钟/参数构成，锁避免重复构建 | 借用输入指纹与资源协调；仍需 OPC 的 job 意图、回执与对账 |
| `~/otpu-build/tv-<name>` / `~/otpu-test/<name>` | 远端运行树；分离测试与构建环境，`.DONE` 与 `.out` 支持轮询 | 远端路径是 job 位置，不应成为永久证据的唯一地址 |

来源：[组件配置](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/components/otpu_coll.yaml)、[目录初始化与基线缓存](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/orchestrator.py#L80-L237)、[候选执行与原件](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/orchestrator.py#L365-L474)、[报告生成](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/report.py#L115-L141)、[远端完成记录](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/remote.py#L322-L354)。

官方说明给出一轮顺序：champion → slot worktree → hypothesis → implementation → 分级 gates → accept rule → 更新 champion → scribe/log → 清理 slot。它明确把主分支合并留给人决定；该策略可以保留为 OPC 的候选接纳与发布分离。[一轮流程与产物说明](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/docs/tourney.md#L31-L75)

## 3. 不能原样继承的边界

1. **ID 与并行隔离。**round ID 是秒级时间，slot 是 `rid-s{k}`；单独用这个路径无法保证多个项目/控制器永不撞名。OPC 应以服务生成 UUID/ULID 为唯一 ID，短序号只作显示。[ID 生成](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/orchestrator.py#L598-L616)
2. **删除与恢复。**`drop()` 会强制移除 worktree、目录和分支，`clean_leftovers()` 会清理旧运行遗留；有锁和 `--keep`，但不是通用持久 job 对账。OPC 只有确认作业结束、证据归档完整并符合保留政策时才可清理；未知作业不得先删工作区。[工作区与清理](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/orchestrator.py#L254-L315)
3. **补丁不等于完整快照。**patch 写入发生在 sandbox 之后；之前的异常可能只有日志。普通 `git diff` 不包含未跟踪文件，因此不能拿一个 patch 保证复现所有候选。OPC 应保存允许范围内的实际源码快照、未跟踪文件清单、内容 hash、基线信息；失败也要冻结。这是从固定代码的保存时机与命令得出的推断。[patch 保存](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/orchestrator.py#L430-L437)
4. **共享缓存不是审计原件。**缓存可能被 prune；Git ignore 也可能排除 agent 轨迹。审计所需日志、配置、评价器和报告必须转入独立 evidence store；临时 build 路径不可成为唯一证据。[缓存清理](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/gates.py#L196-L221)、[忽略规则](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/.gitignore)
5. **本地锁有部署范围。**测试 gate 的 `fcntl` slot 锁与 Vivado start 锁约束当前实现的共享主机；Windows、分布式资源租约和其他调度器需适配，不直接复制 Linux 路径或全局 `/tmp` 文件名。[测试资源锁](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/gates.py#L64-L100)、[构建准入](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/remote.py#L175-L220)
6. **重新测试与历史接纳。**openTPU `--replay` 把旧 patch 应用到当前 champion 再跑 gates；这不是重现原环境。OPC 应同时支持 replay-original（固定旧输入）与 re-evaluate（新基线、新 attempt）；后者不能继承旧审核。[replay 实现](https://github.com/FeSens/openTPU/blob/506e81b1d297e22739dab5ecaeee684493d5c720/tools/tourney/orchestrator.py#L476-L493)

## 4. OPC 建议目录：项目保留原样，接入层只放必要信息

以下已按本轮最终方案统一路径，不是已实现的 OPC daemon。完整约束以 [项目接入与目录规范](../../OPC%20项目接入与目录规范.md) 和 schema 为准。

```text
<target-project>/
  src/ rtl/ compiler/ tests/ ...           # 项目原结构完全保留
  .opc/                                  # 小型、可版本化的接入资产
    project.json                         # project_id、adapter、逻辑路径、能力与范围
    components/<component-id>.json        # 可改范围、冻结参考、test/eval命令映射
    context/                             # PROJECT/REQUIREMENTS/DECISIONS，项目上下文
    tasks/<task-id>/revisions/r0001/       # task.json、TASK.md、CONTEXT.md
    local/                               # Git忽略；本机绑定、缓存、runtime默认位置
      bindings.json                      # 绝对路径/host映射；不放明文密钥
      ledger.sqlite3                     # 未来本机服务的唯一业务账本
      artifacts/                         # 默认证据根，可改为项目外

<workspace-root>/<project-id>/<task-id>/<run-id>/a000001/ # 项目外候选/复核工作区
<artifact-root>/<project-id>/<task-id>/<run-id>/          # 持久证据由此解析
```

`artifact-root` 默认落到 `.opc/local/artifacts`，也可绑定到项目外；`workspace-root` 必须显式配置在项目外，并与项目及证据根互不包含。未来可接远端或对象存储；当前工具仅计算本地路径。外置不复制双写第二套权威原件；本地只保留绑定。Git 里存的是逻辑引用和可共享配置，不是作者机器的盘符/用户名。

普通项目不需要复制 OPC 引擎源码；由版本固定的 CLI/服务读取 `.opc/project.json`。确需自定义 adapter 时，项目仅保存薄封装与版本引用。原有 `AGENTS.md`、构建入口和测试继续生效，不自动覆盖。

如果项目已有 `.planning/`、`docs/specs/`、`experiments/` 等约定，可在配置中映射这些位置；不为满足 OPC 文件名而搬迁已有资产。接入配置只定义唯一权威路径，避免同一需求在两棵目录各维护一份。

## 5. 每次实验的归档单位

```text
<artifact-root>/<project-id>/<task-id>/<run-id>/
  run.json                               # task/revision、基线、配置/环境指纹
  events.jsonl                           # 权威事件的导出，不是第二写入端
  attempts/<attempt-id>/
    plan.json                            # 本轮假设、反证、控制变量、输入与预算
    candidate/source-manifest.json        # 基线 + 实际候选源码快照引用
    candidate/source/                    # 实际源码；patch仅为辅助视图
    experiment/jobs/<job-id>/
      request.json                       # argv/cwd/env引用、输入、幂等键、资源
      receipt.json                       # backend身份、时间、退出码、结算
      stdout.txt / stderr.txt             # 完整原始输出
      outputs/                           # 原始测量/测试/仿真产物
    submissions/<submission-id>/
      manifest.json / submission.json     # 不可变的证据、产物绑定与主张
    reviews/<review-id>/
      request.json / decision.json        # 固定submission绑定、双轴结果
      jobs/<job-id>/...                   # reviewer独立复算原件
    # SUMMARY.md 与对应 submission 同目录
  views/report.json                      # 汇总投影；人读STATE/HANDOFF也在views
```

内容寻址对象可以放在 `objects/sha256/<prefix>/<digest>` 供多次实验去重；manifest 引用 hash，而不是复制大数据。目录只为阅读便利，唯一性由 `project_id/task_id/run_id/attempt_id/job_id/submission_id/review_id` 与未来服务的数据库约束保证。

一次实验失败仍创建 job receipt、记录 stderr 与已产生输出；没有产出的项标缺失，不创建空文件冒充成功。一次设计修订产生新 attempt；同一快照的 reviewer 基础设施重试使用新 review/job ID，但继续引用同一 submission，避免重新跑昂贵实验。并行候选各有 attempt；轮次号仅用于把这些候选分组。

## 6. 路径与跨机器可移植性

合同使用 `project://<project-id>/<repo-relative-path>` 与 `artifact://<project-id>/<task-id>/<run-id>/<relative-path>` 逻辑引用；本机 binding 负责解析成实际绝对路径。project 引用还须绑定基线与摘要。workspace 是服务分配的本地执行位置，不进入共享证据合同。当前工具仅输出 artifact URI，不表示已有生产 resolver 或对象存储适配器。

路径字段不能兼作任意 shell 参数。解析先拒绝绝对路径、`..`、Windows drive/UNC、保留名，再解析符号链接和最终目标，验证其仍在授权根目录；写入时同样验证父目录，防止已有 link 把产物导向别处。模型只能返回逻辑目标，实际存储位置由运行服务分配。

移动项目只改本机 binding，不改所有 TaskSpec 的 hash。跨仓库任务引用多个 project/revision，不能以相同目录名冒充同一资产。对象大小/媒体类型/hash 一起记录；hash 相同仅证明 bytes 相同，不证明访问权限或可信来源。

## 7. 接入步骤与 dirty 项目处理

1. **发现，先只读。**识别项目根、Git/非Git、原有规范、构建/测试/输入路径与工具；输出接入草案和缺口，不自动运行仓库安装脚本。
2. **登记能力。**固定 project_id、adapter 版本、组件/允许修改路径、冻结参考与评测命令、可用资源；不要求统一编程语言或源目录。
3. **选择并冻结基线。**Git 清洁时记录 commit/tree；dirty 时保留原工作区，区分“从明确提交开始”与“包含当前工作区快照”。后者必须记录 staged/unstaged/untracked 的实际纳入列表与 hash，不能只记 HEAD。不能自行 stash/reset/clean、批量 stage 或提交用户文件。
4. **预检与基线实验。**检查依赖、数据可读、评价器可执行、资源已授权；先运行可重复基线并保存证据。原本就失败的测试如实记录，不借改变断言凑通过。
5. **隔离候选。**Git 用基线创建 worktree；非Git用受控源码快照复制，排除本地runtime/cache/凭证，冻结纳入列表。候选只写工作区和分配的 job 输出路径。
6. **启动统一循环。**任务引用 project/config/source fingerprint；每轮证据按稳定 ID 归档，独立 reviewer 使用只读 submission 与自己的 scratch。
7. **交付和清理分开。**accepted 是固定提交在合同下的事实；推广为当前最佳、合入目标仓库、推送/发布有各自显式策略与授权。先验证归档可回取，再按保留策略回收已结束 scratch/cache。失败证据、预算、审核不随落选候选删除。

首次安装/接入的可见产物应是一张接入报告：当前项目指纹、将新增哪些文件、权威状态与产物在哪里、会调用哪些命令、哪些只读、哪些可写、哪些还阻塞。已有授权内可以执行可逆建档，运行外部设备或扩大预算不能由模板默许。

## 8. 本轮可落地的最小改进

先增加 **ProjectConfig + 项目接入说明 + 每轮产物约定**，把原方案只描述 OPC 自身源码目录的不足补齐。给软件项目、编译/仿真项目、RTL项目各保留一份 adapter 配置样例即可，不先安装三个完整执行平台。

目录与模板验证至少应覆盖：已有项目文件不覆盖；重复初始化不分裂project_id；配置引用缺失会预检失败；产物和worktree不会落进用户源码；多任务attempt路径不碰撞；dirty基线与非Git快照不能被写成纯commit基线；移动根目录后逻辑引用仍能解析；未知活作业不能被清理。真正执行、权限隔离与远端恢复应另做真实后端集成验收。
