---
name: archa-loop
description: 用户要求从已确认的 task-brief 启动或恢复 ArcHa 自动迭代时使用；定位对应合同，完成执行检查，调用项目内引擎并报告结果。
---

# 从简报启动自动迭代

调用：`archa-loop <task-brief-path>`（技能提示词可写 `$archa-loop <task-brief-path>`）。这是技能入口，底层复用项目 `.opc/archa.py` 的命令。

## 定位任务

解析简报真实路径，从其祖先目录定位包含 `.opc/archa.py` 的项目根目录；路径有空格时引用完整参数。使用可用的 Python 3.10+（Windows 通常是 `python`，下文以 `python3` 示意）。先读项目约定和本地 CLI `--help`，再运行：

```bash
python3 <project>/.opc/archa.py brief-check -p <project> --brief <brief>
```

读取 `.opc/context/DECISIONS.md` 的交接记录，按简报相对路径和 SHA-256 找到 task ID、revision、合同路径；核对实际合同与简报的目标和验收条件。摘要变化、对应关系缺失或存在歧义时先解决交接，不猜测 `t-main` 或默认最新 revision。旧项目可从合同和 context 的明确来源关系补记交接；无法唯一确认时说明缺项。brief 校验失败或尚未 onboard 时交回 archa-task 完成合同准备。

## 准备执行

用户要求启动本技能即授权在已确定的合同范围、预算内准备和运行，无需重复询问是否启动。先核对 `.opc/README.md` 的 Open items、交接记录及实际合同；预算未定或可靠用量记录不可得时停止新增派发；评价器、负控、证据工具或设备能力未知属于范围内准备待办，先用下述 prepare 路径自主建立与验证，不直接转交用户。不得编造指标或扩大范围。

读取 `status -p <project> --task <task-id>`。已有控制器运行时只跟踪状态，不启动第二个控制器。相同 revision 的 paused/blocked run 在原因解决后可用普通 run 恢复；closed run 默认报告已有结果，不自动用 `--new-run` 重置预算。用户明确要求新一轮且预算已确定时才使用 `--new-run`；合同变更也需要新 run，只有明确从上次冠军继续时才传 `--base <冠军提交>`。

首次执行准备时打开 `.opc/project.json` 的 `execution_enabled`，然后按顺序完成：

1. `check -p <project> --task <task-id> --revision <revision>`，处理合同问题；未提交接入文件及因此未进入基线的评价器留到下一步解决。
2. 检查 Git 差异，仅提交本次执行所需、已核对的接入文件，使合同与评价器在基线中可用。保留用户其他修改和暂存内容；存在无法分离的修改时说明阻塞，不用整体暂存或清理工作区解决。遵守项目提交约定。
3. 重跑 check，要求全部通过，再运行 `preflight -p <project> --task <task-id> --revision <revision>`，确认执行通道工作；无 objective 时功能门失败可作为未完成基线，保留失败事实。工具、输入和输出契约故障仍阻塞。明确的环境问题可在授权范围内修复；需要更改冻结评价标准或目标时先回到合同修订。

检查或 preflight 失败时不启动 run；如果本次才打开执行开关且准备失败，将其恢复为关闭并如实记录。恢复已有 run 时保持其冻结合同，仍核对 check 和环境，不为了通过检查原地改动旧 revision。

## 运行与交付

```bash
python3 <project>/.opc/archa.py run -p <project> --task <task-id> --revision <revision>
```

由引擎完成决策、候选执行、评价、接纳与反馈，沿用合同方向和预算。跟踪进程及 `status`，直到完成、暂停或阻塞；预算耗尽、搜索枯竭和用户暂停都应保留，不自动反复重启。用户要求暂停或停止时调用对应 `pause` / `stop` 命令，等引擎确认状态。

结束后调用 `report -p <project> --task <task-id> --revision <revision>`，报告实际 run/revision、停止原因、目标达成情况、冠军提交与指标、交付物及报告路径、剩余问题。区分“达到目标”和“预算内最好结果”；本技能不自动 promote 到用户分支。

无 objective 时默认从工作版本继续；有 objective 保持冠军默认起点，expert 可用 base_attempt 选择任何已保存候选，也可在停止时选版。run 停止与任务完成分开；promote 对选定版本执行完整验收及合同所需 review，未满足条件不得声明完成。独立 review 回执不需要新 designer 候选。

## 自主准备与冻结

发现准备待办时使用已有 onboard 命令的 `--prepare --task <task-id> --brief <brief> --max-tokens <授权总额> --max-wall-seconds <授权秒数> --prior-wall-seconds <累计主流程及外部嵌套秒数> --prior-tokens <累计主流程及外部嵌套用量>`。总量包含 cached input，不能填猜测的 0；正常 worker 与只读 reviewer 由 ledger 自动记账，不重复计入 prior-tokens。未知用量停止新增派发。准备与正式 run 共用同一授权总额，不能新建 run 重置。
准备 agent 可在 .opc 内建立评价器、负控、原件采集/保存与监控工具，进行授权的有界设备能力探测；不自动开展正式手机实验。未探测不是外部阻塞，失败须保留命令、权限错误与原始回执。pending 表示 agent 继续准备；ready 只表示审阅通过，正式实验尚未开始；external_blocked 必须给出观测证据、缺失外部条件、责任人与下一步。
准备调用后只读 reviewer 核对需求、评价器及负控回执，审阅通过的文件摘要在既有 ledger 中冻结。提交被审文件，check/preflight 通过且用户允许正式执行才进入 run。“本步只准备”时到此结束，不能自动启动设备实验。产品未实现的功能失败是未完成基线，不能变造评分过门。
已有正式 run 时不原地改冻结合同/评价器：保留旧 revision/run，准备新 revision 并重新审阅冻结；预算账本沿用。旧部署 runtime/全局技能不会自动更新，先核对入口 --help 是否支持 --prepare，不以仓库源码代替已安装行为。
