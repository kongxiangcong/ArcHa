---
name: archa-task-brief
description: 读取 research-map 的任务清单，每次选择一个研究任务，派 sub-agent 调研源码或外部原始来源，调研后提出 brief 大纲供用户确认，确认后生成 task-brief.md，供 ArcHa onboard 起草合同。
---

# 单个研究任务的背景与简报

输入 research-map.md 路径。只给目录时查找其 `.opc/research/research-map.md`；找不到时说明需要先用 `$archa-research-map` 形成地图，不凭空补全方向。

## 选择一个任务

读取地图、`discussion.md` 和任务占位文件。先检查 `parked` 项的重开条件，满足时记录依据并恢复 `todo`；再优先用户指定 ID，其次继续 `active` 的任务，否则选清单中首个依赖已满足的 `todo` 项。本次只推进一个任务。上游简报就绪不代替依赖所需的研究结果；全部已 ready 时报告可交接，不重复调研。

用户指定的任务依赖不足时解释缺口，可以先厘清它的前置问题，但不假装依赖已满足。全部 parked 时给出最先缺少的东西和建议下一步。

## 派 sub-agent 调研

把选中项设为 `active`，在任务目录创建 `evidence/`。优先为当前任务派 sub-agent：按问题选择外部原始来源搜索、当前项目源码调查或两者。发给它地图相关段落、任务用途、要检验的前提、项目路径和证据输出要求，不预先给期望结论。没有可用 sub-agent 时由主 agent 自查，并在证据中如实标注。

sub-agent 只调查本任务，不改项目实现、地图状态或执行合同，按 [证据约定](references/evidence.md) 写证据。调查目的是界定目标范围，不是开始正式研究或实现。主 agent 核对会改变范围的关键证据。

## 澄清并展示建议大纲

先读 [简报模板](references/task-brief.md) 和 [ArcHa 消费链](references/archa-workflow.md)。

只对会改变用途、范围或交付物的缺口逐步提问，一次一个关键问题，附建议和理由；用户不清楚时先给例子或继续调查。常规实现选择给出建议，基线、预算、worker、引擎适配等留给 onboard，不把这些细节逐项变成收口障碍。

背景足以界定任务后，在最终回复中给出一份可审阅的**建议 brief 大纲**，而不是只报告调研进度或追问下一个细节。大纲包括：

- 任务 ID、问题与用途。
- 一句话目标（Goal）、完成状态（Done when）和大致路线（Direction）。
- 当前证据支持的判断与关键缺口。
- 包含与排除的范围。
- 可辨认的交付物（D*）、验收条件（R*，注明 automated/review 及评价器是否已有），以及有没有数值指标（Objective，没有就说明原因）。
- 什么发现会调整目标，以及建议留给 onboard 的未决项。

目标和验收条件可以暂定，但必须写出来；“怎么做”的细节不必在大纲里定。

大纲末尾请用户检查是否需要修改，并确认是否按此生成简报。用户确认的是这份整体大纲（包括明确列出的起草阶段未决项），无需再逐项重复确认。用户提出修改时，吸收修改并展示修订后的大纲，等待确认；仅回答局部问题或未回复不算认可整份大纲。已有明确认可当前大纲的会话记录时直接继续。

## 确认后生成与交接

确认前只保存 evidence 和 `discussion.md` 中的大纲、用户决定及待确认状态；清单保持 `active`、未勾选，不创建 `task-brief.md`。若已有历史简报，保留内容；重新讨论时可标记 `Status: draft` 并记录修订原因，正文改稿仍待新大纲确认。

用户确认大纲后，依据确认内容生成或更新 `task-brief.md`，设为 `Status: ready-for-onboard`；在 Source 中记录确认依据，在 Open decisions 中保留大纲已列出的起草阶段未决项。未知项写“未知 + 原因”，不臆造数值。随后运行

```bash
python3 /absolute/project/.opc/archa.py brief-check -p /absolute/project --brief .opc/research/tasks/<task>/task-brief.md
```

通过后在地图勾选该项并设为 `ready-for-onboard`，链接简报，明确“简报已完成，研究尚未执行”，给出范围、未决事项和建议下一步。检查失败则保持未勾选并修复。结构通过不证明研究设计正确。

默认结束于本任务简报，不自动处理下一个 task 或调用 onboard。用户要求起草合同时运行 `python3 /absolute/project/.opc/archa.py onboard -p /absolute/project --brief <brief>`，之后核对合同与 Open items，保持执行关闭。