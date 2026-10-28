---
name: archa-task
description: 读取 research-map 的任务清单，调查一个任务并提出 brief 大纲；依据用户需求自主生成 task-brief.md，自动调用 ArcHa onboard 并核对合同，为 archa-loop 准备执行入口。
---

# 单个研究任务的背景与简报

输入 research-map.md、已确认任务或简报路径。明确工程任务可直接接入，无需先建地图；来源使用 `Task: <项目相对的任务文件>`。缺少 runtime 时复用 archa-map/scripts/initialize.py 的项目初始化能力，不生成空地图。已有调查和确认简报直接复用，仅核对关键依据和交接；只有范围仍不明确时继续讨论。

## 选择一个任务

有地图时读取相关段落、`discussion.md` 和任务占位文件；直接任务读取其需求和现有调查。先检查 `parked` 项的重开条件，满足时记录依据并恢复 `todo`；再优先用户指定 ID，其次继续 `active` 的任务，否则选清单中首个依赖已满足的 `todo` 项。本次只推进一个任务。上游简报就绪不代替依赖所需的研究结果；全部已 ready 时报告可交接，不重复调研。

用户指定的任务依赖不足时解释缺口，可以先厘清它的前置问题，但不假装依赖已满足。全部 parked 时给出最先缺少的东西和建议下一步。

## 派 sub-agent 调研

把选中项设为 `active`，在任务目录创建 `evidence/`。仅在已有证据不足时为当前任务派 sub-agent：按问题选择外部原始来源搜索、当前项目源码调查或两者。发给它地图相关段落、任务用途、要检验的前提、项目路径和证据输出要求，不预先给期望结论。没有可用 sub-agent 时由主 agent 自查，并在证据中如实标注。

sub-agent 只调查本任务，不改项目实现、地图状态或执行合同，按 [证据约定](references/evidence.md) 写证据。调查目的是界定目标范围，不是开始正式研究或实现。主 agent 核对会改变范围的关键证据。

## 澄清并展示建议大纲

需要跨 run 接续的研究任务，在简报交付物中指定一个稳定成果 README，优先引用已有 specs、批次和 evidence-index；沿用已有入口。将该路径交给 onboard 写入可选 `results_path`。结论正文及适用条件留在 specs，无 specs 时写在 README。新增验收条件按合同 revision 流程处理；历史批次缺失计划或审核时如实标记，不补造材料。

先读 [简报模板](references/task-brief.md) 和 [ArcHa 消费链](references/archa-workflow.md)。

根据用户需求、现有材料和调查证据自主补齐任务；常规选择直接落实，合理假设与未决项写入 discussion.md。默认不停下来提问，不将大纲或预算作为额外确认关卡。真实无法解决的外部条件如实报告，不把沉默记作用户确认。

背景足以界定任务后，形成可审阅的 **brief 大纲**并继续生成简报，而不是只报告调研进度或追问下一个细节。大纲包括：

- 任务 ID、问题与用途。
- 一句话目标（Goal）、完成状态（Done when）和大致路线（Direction）。
- 当前证据支持的判断与关键缺口。
- 包含与排除的范围。
- 可辨认的交付物（D*）、验收条件（R*，注明 automated/review 及评价器是否已有），以及有没有数值指标（Objective，没有就说明原因）。
- 什么发现会调整目标，以及建议留给 onboard 的未决项。

目标和验收条件可以暂定，但必须写出来；“怎么做”的细节不必在大纲里定。

把大纲、依据和合理假设保存到 discussion.md 后，直接生成或更新 task-brief.md 并自动 onboard，无需停下来等待大纲确认。用户已给出的约束优先；新需求与冻结验收冲突时保留旧 revision，按修订流程处理。

## 生成与交接

依据用户任务与调查结果生成或更新 `task-brief.md`，设为 `Status: ready-for-onboard`；Source 记录用户任务来源及采用的假设，Open decisions 保留必要待办。未知项写“未知 + 原因”，不臆造数值。已有历史简报和证据保留。

随后运行

```bash
python3 /absolute/project/.opc/archa.py brief-check -p /absolute/project --brief .opc/research/tasks/<task>/task-brief.md
```

有地图时，通过后在地图勾选该项并设为 `ready-for-onboard`，链接简报；该状态仅表示简报就绪，不表示合同或执行就绪。检查失败则保持未勾选并修复。结构通过不证明研究设计正确。

## 自动完成 onboard

简报检查通过后，先检查 `.opc/context/DECISIONS.md` 是否已有同一简报路径及摘要、且合同核对完成的交接；有则复用并核对当前合同。否则直接运行，无需用户再发起 onboard：

```bash
python3 /absolute/project/.opc/archa.py onboard -p /absolute/project --brief <brief> --prepare --task <task-id>
```

使用项目已有的起草 worker 配置（CLI 默认 codex，需要 dsh 时加 `--agent dsh`）。核对返回的 `ok`、越界修改和受保护输入变化；失败时保留诊断，修复明确原因后再继续，不把 worker 返回成功当作合同完成。

依据消费链核对目标、交付物、验收条件、评价器、范围、基线、预算与 worker。自动解决已确认范围内能从证据确定的事项；只将超出已授权范围的事项或有实际证据的外部条件列为 external_blocked；必要评价器接入、关键失败路径、证据采集和未知设备能力列为 pending，由当前 agent 在预算内开发核验，不要求另建任务。保持 `execution_enabled=false`，用项目入口运行 `check -p <project> --task <task-id> --revision <revision>`。执行关闭、接入文件尚未提交以及因此尚未进入基线的评价器属于待 loop 完成的准备项；其他问题修复或列为阻塞，不把所有非零退出都当作预期。不运行 preflight 或 run。

在 `.opc/context/DECISIONS.md` 记录本次交接：简报的项目相对路径及当前 SHA-256、对应 task ID、revision、合同路径、已定执行预算和剩余阻塞项。从实际生成的合同核对 ID，不把地图 ID 当作引擎 ID。保留其他任务记录。已投入执行的合同修改沿用新 revision/run 流程。

最后给出简报、合同位置和准备状态；有阻塞时说明缺项，无阻塞时给出 `$archa-loop <task-brief绝对路径>`。本次结束于本任务的合同准备，不自动启动 loop 或处理下一个任务。

## 自主准备与冻结

预算与模型统一配置在 `.opc/local/workers.json` 的 `budget` 对象：`max_tokens`、`max_wall_seconds` 默认 `null`（无上限），可分别设置。仅用户明确给出相应上限时写入数值；保留已有明确配置，不从模板、历史实验或 agent 估算生成限制，不为预算停下来提问。正常推进已授权工作，持续记录实际用量；无上限时缺失计量只标为 unknown，不阻塞执行。显式 token 上限要求可靠累计 token，显式时间上限要求可靠累计时间；无法自主恢复必要计量时报告实际阻塞。保留用户 pause/stop、真实外部权限和冻结验收边界。


发现准备待办时使用已有 onboard 命令的 `--prepare --task <task-id> --brief <brief>`。有可靠计量时附加 --prior-tokens / --prior-wall-seconds 更新累计主流程用量（包含 cached input），不重复计算 ledger 已记录的 worker/reviewer。无记录时保留 unknown，不填猜测的 0。显式上限下准备与正式 run 共用累计消耗，不能新建 run 重置。
准备 agent 可在 .opc 内完成必要评价器、关键失败路径与原件采集接入，进行授权的有界设备能力探测；不自动开展正式手机实验。未探测不是外部阻塞，失败须保留命令、权限错误与原始回执。pending 表示 agent 继续准备；ready 只表示必要接入检查完成，正式实验尚未开始；external_blocked 必须给出观测证据、缺失外部条件、责任人与下一步。
准备默认不调用 reviewer；合同 preparation_review=true 时进行针对性独立审核。当前任务及实际共享评价依赖摘要在 ledger 中冻结。提交被审文件，check/preflight 通过且用户允许正式执行才进入 run。“本步只准备”时到此结束，不能自动启动设备实验。产品未实现的功能失败是未完成基线，不能变造评分过门。
已有正式 run 时不原地改冻结合同/评价器：保留旧 revision/run，准备新 revision 并重新审阅冻结；预算账本沿用。旧部署 runtime/全局技能不会自动更新，先核对入口 --help 是否支持 --prepare，不以仓库源码代替已安装行为。

每次交给正式 run 或终验 reviewer 前，主流程用相同 onboard 参数加 `--record-usage` 更新最新累计主流程/外部嵌套 token 和耗时；此选项只记账、不调用 worker 或重复审阅，沿用已有冻结回执。缺失计量按上述预算策略处理；无上限时直接继续。


准备默认仅执行与本次接入改动对应的必要检查，不固定建设全套负控或通用监控工具。ready 表示必要接入完成，不代表研究结论成立。合同显式设置 `preparation_review: true` 时保留独立准备审核；旧 ready 回执继续有效。冻结仅覆盖当前 task、component 及 evaluator_files（显式共享依赖也在这些 glob 中登记）。
