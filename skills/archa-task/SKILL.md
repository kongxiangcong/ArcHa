---
name: archa-task
description: 以具体任务目录为必需输入，读取所属地图，调查该任务并提出 brief 大纲；依据用户需求自主生成 task-brief.md，自动调用 ArcHa onboard 并核对合同，为 archa-loop 准备执行入口。
---

# 单个研究任务的背景与简报

必需输入具体任务目录（绝对路径，或相对当前工作目录的明确路径）。缺少路径时只提示“请提供具体任务目录”；项目根、专题根、tasks 集合目录均提示改为具体任务目录，不自动选择任务。旧文件式输入只提示使用所属任务目录。不得按最近使用、唯一专题、active/todo 或最新合同猜测。

## 读取指定任务

读取目录内 task.md 和 task-brief.md（如已有），按 task.md 明确的地图链接读取所属地图及 discussion.md。标准布局可核对上两级的 research-map.md；旧 `.opc/research/tasks/<task>/` 和有明确 task 来源的外置目录保持原位置。明确工程任务无需先建地图，简报 Source 使用 `Task: <项目相对任务文件>`。读取依赖和 parked 重开条件，缺口留在本任务，不自动准备其他任务。缺少 runtime 时复用 archa-map/scripts/initialize.py，不生成空地图。

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
python3 /absolute/project/.opc/archa.py brief-check -p /absolute/project --brief .opc/research/topics/<topic>/tasks/<task>/task-brief.md
```

有地图时，通过后在地图勾选该项并设为 `ready-for-onboard`，链接简报；该状态仅表示简报就绪，不表示合同或执行就绪。检查失败则保持未勾选并修复。结构通过不证明研究设计正确。

## 自动完成 onboard

简报检查通过后运行相邻 archa-map 技能的辅助脚本：

```bash
python3 /absolute/path/to/archa-map/scripts/research.py resolve --project /absolute/project --directory "<任务绝对目录>" --prepare
```

先读取旧合同/context 的明确来源关系；旧式关系存在但脚本无法解析时先核对并 record 补记，不能当作新任务。再按简报项目相对路径定位 DECISIONS 关系，再核对摘要与实际合同。复用返回的 task_id（包括旧 ID）；摘要变化仍沿同一身份走现有 revision 流程，不新建任务。无关系时脚本生成不冲突的可读 ID；若提示存在旧式交接，先读取其明确来源关系，核对合同后用 record 补记，不能绕过歧义。脚本先在 DECISIONS 预留身份，重试仍复用；全新项目先用既有 init 创建该 ID 的合同骨架，再记录预留。骨架不等于已核对合同。使用返回的 task_id 显式执行 onboard，绝不能省略 --task 落入 t-main。新任务在已有项目中由 onboard worker 起草新合同；已有关系不修改其他任务。同一路径、摘要与已核对合同均未变化时直接复用并核对，不重复起草；仅新任务或需要更新时执行下列 onboard。无需用户手动分配 ID 或再次发起 onboard：

```bash
python3 /absolute/project/.opc/archa.py onboard -p /absolute/project --brief <brief> --prepare --task <task-id>
```

使用项目已有的起草 worker 配置（CLI 默认 codex，需要 dsh 时加 `--agent dsh`）。核对返回的 `ok`、越界修改和受保护输入变化；失败时保留诊断，修复明确原因后再继续，不把 worker 返回成功当作合同完成。

依据消费链核对目标、交付物、验收条件、评价器、范围、基线、预算与 worker。自动解决已确认范围内能从证据确定的事项；只将超出已授权范围的事项或有实际证据的外部条件列为 external_blocked；必要评价器接入、关键失败路径、证据采集和未知设备能力列为 pending，由当前 agent 在预算内开发核验，不要求另建任务。保持 `execution_enabled=false`，用项目入口运行 `check -p <project> --task <task-id> --revision <revision>`。执行关闭、接入文件尚未提交以及因此尚未进入基线的评价器属于待 loop 完成的准备项；其他问题修复或列为阻塞，不把所有非零退出都当作预期。不运行 preflight 或 run。

核对完成后运行 `research.py record --project <project> --directory "<任务绝对目录>" --task <实际task-id> --revision <实际revision>`，在 `.opc/context/DECISIONS.md` 追加可解析交接（不另建映射文件）。仅在已核对合同后执行 record；旧式明确关系补记同样需要核对。记录内容包括：简报的项目相对路径及当前 SHA-256、对应 task ID、revision、合同路径、已定执行预算和剩余阻塞项。从实际生成的合同核对 ID，不把地图 ID 当作引擎 ID。保留其他任务记录。已投入执行的合同修改沿用新 revision/run 流程。

最后给出简报、合同位置和准备状态；有阻塞时说明缺项，无阻塞时给出 `$archa-loop "<任务绝对目录>"`。本次结束于本任务的合同准备，不自动启动 loop 或处理下一个任务。

## 自主准备与冻结

预算配置细节见任务项目 `.opc/ONBOARDING.md` 的“独立的 worker 环境配置”：按 Task 累计准备及所有 Run，默认 token 无上限、时间额度两小时。仅在明确授权时调整总额度，保留已用量和已有硬限制；不为默认预算提问。仅对启用的约束要求可靠计量，实际缺失时先自主修复，再报告具体阻塞。保留用户 pause/stop、真实外部权限和冻结验收边界。


发现准备待办时使用已有 onboard 命令的 `--prepare --task <task-id> --brief <brief>`。有可靠计量时附加 --prior-tokens / --prior-wall-seconds 更新累计主流程用量（包含 cached input），不重复计算 ledger 已记录的 worker/reviewer。无记录时保留 unknown，不填猜测的 0。显式上限下准备与正式 run 共用累计消耗，不能新建 run 重置。
准备 agent 可在 .opc 内完成必要评价器、关键失败路径与原件采集接入，进行授权的有界设备能力探测；不自动开展正式手机实验。未探测不是外部阻塞，失败须保留命令、权限错误与原始回执。pending 表示 agent 继续准备；ready 只表示必要接入检查完成，正式实验尚未开始；external_blocked 必须给出观测证据、缺失外部条件、责任人与下一步。
准备默认不调用 reviewer；合同 preparation_review=true 时进行针对性独立审核。当前任务及实际共享评价依赖摘要在 ledger 中冻结。提交被审文件，check/preflight 通过且用户允许正式执行才进入 run。“本步只准备”时到此结束，不能自动启动设备实验。产品未实现的功能失败是未完成基线，不能变造评分过门。
已有正式 run 时不原地改冻结合同/评价器：保留旧 revision/run，准备新 revision 并重新审阅冻结；预算账本沿用。旧部署 runtime/全局技能不会自动更新，先核对入口 --help 是否支持 --prepare，不以仓库源码代替已安装行为。

每次交给正式 run 或终验 reviewer 前，主流程用相同 onboard 参数加 `--record-usage` 更新最新累计主流程/外部嵌套 token 和耗时；此选项只记账、不调用 worker 或重复审阅，沿用当前候选的准备回执。缺失计量按上述预算策略处理。


准备默认仅执行与本次接入改动对应的必要检查，不固定建设全套负控或通用监控工具。ready 表示必要接入完成，不代表研究结论成立。合同显式设置 `preparation_review: true` 时保留独立准备审核；旧 ready 回执继续有效。冻结仅覆盖当前 task、component 及 evaluator_files（显式共享依赖也在这些 glob 中登记）。
