---
name: archa-loop
description: 用户要求从具体任务目录内已确认的 task-brief 启动或恢复 ArcHa 自动迭代时使用；定位对应合同，完成执行检查，调用项目内引擎并报告结果。
---

# 从简报启动自动迭代

调用：`archa-loop <task-directory>`（技能提示词可写 `$archa-loop <task-directory>`）。这是技能入口，底层复用项目 `.opc/archa.py` 的命令。

## 定位任务

必需输入具体任务目录，接受绝对路径或相对当前工作目录的明确路径。缺少时只提示补充具体任务目录；项目根、专题根、tasks 集合目录及文件输入不运行，文件输入提示所属任务目录。不得根据当前目录、最近记录或唯一专题选择任务。

从指定目录定位 task-brief.md，再从祖先目录定位项目根；路径有空格时引用完整参数。使用可用的 Python 3.10+（Windows 通常是 `python`，下文以 `python3` 示意）。先读项目约定和本地 CLI `--help`，再运行：

```bash
python3 <project>/.opc/archa.py brief-check -p <project> --brief <brief>
```

运行 `python3 /absolute/path/to/archa-map/scripts/research.py resolve --project <project> --directory "<任务绝对目录>"`。读取 `.opc/context/DECISIONS.md` 的交接记录，先按简报相对路径找身份，再核对 SHA-256，取得 task ID、revision、合同路径；核对实际合同与简报的目标和验收条件。摘要变化、对应关系缺失或存在歧义时先解决交接，不猜测 `t-main` 或默认最新 revision。旧项目可从合同和 context 的明确来源关系补记交接；无法唯一确认时说明缺项。brief 缺失、摘要变化、校验失败或尚未 onboard 时给出 `$archa-task "<任务绝对目录>"` 完成合同准备。真实绑定歧义说明缺项，不改用其他任务。

## 准备执行

若合同有 `results_path`，先执行 `results -p <project> --task <task-id> --revision <revision>` 阅读当前成果、来源与缺项；入口不存在时加 `--initialize` 建最小模板。后续接续沿用同一入口。原生 run 自动登记执行事实；主流程在已有解释步骤更新 README 人工区和所引用 specs：主张、适用条件、证据、未知项、下一步，明确待审核或被替代的结论。保持自动登记区完整。

主会话自行执行批次时，在执行前与执行后调用同一个 `results --batch <稳定批次ID> --experiment-id <稳定问题ID>` 入口，用 `--plan/--evidence/--analysis/--review` 引用原位置，路径相对成果 README。按事实使用 `--status planned|running|completed|failed|aborted|cached`；已有批次 ID 可复用，外部批次没有 run。执行前记录问题、对照、竞争预测与判定方式，结果不同于预期或证据不足均可正常登记。缓存仅表示历史证据。

登记失败后用 `results --sync-run <run-id>` 重建引擎登记，外部批次重发相同登记命令；两者均不重新实验。变更累计结论时保留原件及旧版本，说明变化原因，并使旧审核继续仅覆盖旧对象；引用具体 promotion/report.json，不能把 run 通过当成逐条科学主张已审核。通过现有研究解释流程完成这些更新，无需为了收尾另派模型或 reviewer。

用户要求启动本技能即授权在已确定的合同范围、预算内准备和运行，无需重复询问是否启动。先核对 `.opc/README.md` 的 Open items、交接记录及实际合同；未设置预算时按 token 无上限、Task 时间额度两小时继续；必要评价器接入、关键验证或设备能力未知属于范围内准备待办，先用下述 prepare 路径自主建立与验证，不直接转交用户。不得编造指标或扩大范围。

读取 `status -p <project> --task <task-id>`。已有控制器运行时只跟踪状态，不启动第二个控制器。继续执行使用 `run --run-id <run-id>`，按原 Run 的冻结 revision/配置恢复。只存在一个可续接 Run 时可自动选择；多个候选须指定 ID，不能按最新 revision 或时间猜测。status 只读取状态，保留 pause/stop。closed Run 返回原结果，不原地重开，也不自动用 `--new-run` 重置预算；已登记失败终验的范围内修复使用下文 --repair-promotion，属于同一授权任务。用户明确要求新一轮时才使用 `--new-run`；合同变更也需要新 run，只有明确从上次冠军继续时才传 `--base <冠军提交>`。

首次执行准备时打开 `.opc/project.json` 的 `execution_enabled`，然后按顺序完成：

1. `check -p <project> --task <task-id> --revision <revision>`，处理合同问题；未提交接入文件及因此未进入基线的评价器留到下一步解决。
2. 检查 Git 差异，仅提交本次执行所需、已核对的接入文件，使合同与评价器在基线中可用。保留用户其他修改和暂存内容；存在无法分离的修改时说明阻塞，不用整体暂存或清理工作区解决。遵守项目提交约定。
3. 重跑 check，要求全部通过，再运行 `preflight -p <project> --task <task-id> --revision <revision>`，确认执行通道工作；无 objective 时功能门失败可作为未完成基线，保留失败事实。工具、输入和输出契约故障仍阻塞。明确的环境问题可在授权范围内修复；需要更改冻结评价标准或目标时先回到合同修订。

检查或 preflight 失败时不启动 run；如果本次才打开执行开关且准备失败，将其恢复为关闭并如实记录。恢复已有 run 时保持其冻结合同，仍核对 check 和环境，不为了通过检查原地改动旧 revision。

## 运行与交付

```bash
python3 <project>/.opc/archa.py run -p <project> --task <task-id> --revision <revision> --deliver
```

由引擎完成决策、候选执行、评价、接纳与反馈，沿用合同方向和预算。跟踪进程及 `status`，直到完成、暂停或阻塞；预算耗尽、搜索枯竭和用户暂停都应保留，不自动反复重启。用户要求暂停或停止时调用对应 `pause` / `stop` 命令，等引擎确认状态。

结束后调用 `report -p <project> --task <task-id> --revision <revision>`，报告实际 run/revision、停止原因、目标达成情况、冠军提交与指标、交付物及报告路径、剩余问题。区分“达到目标”和“预算内最好结果”；终验通过仅交付报告和 selected commit；不自动 apply 到用户分支。

无 objective 时默认从工作版本继续；有 objective 保持冠军默认起点，expert 可用 base_attempt 选择任何已保存候选，也可在停止时选版。run 停止与任务完成分开；promote 对选定版本执行完整验收及合同所需 review，未满足条件不得声明完成。独立 review 回执不需要新 designer 候选。

## 自主准备与冻结

预算配置细节见任务项目 `.opc/ONBOARDING.md` 的“独立的 worker 环境配置”：按 Task 累计准备及所有 Run，默认 token 无上限、时间额度两小时。仅在明确授权时调整总额度，保留已用量和已有硬限制；不为默认预算提问。仅对启用的约束要求可靠计量，实际缺失时先自主修复，再报告具体阻塞。保留用户 pause/stop、真实外部权限和冻结验收边界。


发现准备待办时使用已有 onboard 命令的 `--prepare --task <task-id> --brief <brief>`。有可靠计量时附加 --prior-tokens / --prior-wall-seconds 更新累计主流程用量（包含 cached input），不重复计算 ledger 已记录的 worker/reviewer。无记录时保留 unknown，不填猜测的 0。显式上限下准备与正式 run 共用累计消耗，不能新建 run 重置。
准备 agent 可在 .opc 内完成必要评价器、关键失败路径与原件采集接入，进行授权的有界设备能力探测；不自动开展正式手机实验。未探测不是外部阻塞，失败须保留命令、权限错误与原始回执。pending 表示 agent 继续准备；ready 只表示必要接入检查完成，正式实验尚未开始；external_blocked 必须给出观测证据、缺失外部条件、责任人与下一步。
准备默认不调用 reviewer；合同 preparation_review=true 时进行针对性独立审核。当前任务及实际共享评价依赖摘要在 ledger 中冻结。提交被审文件，check/preflight 通过且用户允许正式执行才进入 run。“本步只准备”时到此结束，不能自动启动设备实验。产品未实现的功能失败是未完成基线，不能变造评分过门。
已有正式 run 时不原地改冻结合同/评价器：保留旧 revision/run，准备新 revision 并重新审阅冻结；预算账本沿用。旧部署 runtime/全局技能不会自动更新，先核对入口 --help 是否支持 --prepare，不以仓库源码代替已安装行为。

每次交给正式 run 或终验 reviewer 前，主流程用相同 onboard 参数加 `--record-usage` 更新最新累计主流程/外部嵌套 token 和耗时；此选项只记账、不调用 worker 或重复审阅，沿用当前候选的准备回执。缺失计量按上述预算策略处理。


## 自动终验与修复消费顺序

`run --deliver` 在自然结束后终验明确的 source run。读取返回的 delivery.complete；只有 true 才报告任务完成。未产生终验或 delivery_error 均为未完成。

1. 普通可修复 findings：用 `run ... --repair-promotion <report_dir>/report.json --deliver` 从失败报告的 selected commit 续接，沿用同 task 累计预算，不重启旧 run、不创建新 task。具体 findings 进入新 run direction。
2. 仅 reviewer 不可用/输出格式错误：用 `promote ... --source-run <run-id> --review <configured-provider>` 重试审核，不调用 designer。沿用 max_consecutive_infra 和总预算；达到限制停止并报告未完成。
3. 若修复后 selected commit 未变化且 findings 相同，不再次修复或重审；仅具体修复、外部状态变化或用户确认新标准后继续。
4. 用户 pause/stop、显式预算耗尽或显式 token 限制下 accounting_unknown 时停止新增派发。用户仅要求准备时不进入本流程。
5. scope/evaluator 变化需要明确的新 revision；验收含义变更须用户明确确认。所有终验命令默认不传 --apply。


## 用户确认标准修订

用户明确给出旧要求与新要求后，保存新 task revision，保留原 revision/run/失败报告。纯验收修订使用 `promote ... --revision <new-revision> --source-run <old-run> --standards-confirmation <confirmation.json>`。确认文件格式和字段见仓库 docs/design/task-delivery/spec.md 的实施说明；不能从 reviewer 建议或用户沉默生成确认。

旧 candidate 与 evaluator 不变时复用仍适用的测量，重新判定；required=false 仅将明确诊断要求及其独占 gates 降为诊断，其他未声明 gates 和必需要求默认仍硬性阻断。目标、执行输入、评价器或预算改变须走新冻结 revision/run，不能经此入口放行。
