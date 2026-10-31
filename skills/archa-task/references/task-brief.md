# task-brief 模板（仅第二阶段）

依据用户任务与调查结果直接生成简报，合理假设记录在 discussion.md，无需等待额外大纲确认。保留六个二级英文标题和带前缀的字段行（`Map:`、`Status:`、`Goal:`、`Done when:`、`Direction:`、`- D1:`、`- R1:`、`Objective:` 等），字段值和其余正文可用中文自由书写；Map 是相对目标项目根目录的真实文件路径，不带 Markdown 链接或行号。

“做什么”要明确，“怎么做”留白：目标、完成状态、交付物和验收条件必须写出来，可以是当前证据下的暂定版本，随后续证据调整；基线 ref、可改/冻结路径、预算、worker、自主权边界和引擎适配属于 onboard 起草合同的工作，已知的约束写进 Open decisions 供起草参考。

字段与合同的对应：`Goal` → `task.goal`，`Direction` → `task.direction`，`R*` → `task.requirements[]`，`Objective` → `acceptance.objective`。任务没有自然数值目标时写 `Objective: none: <原因>`，映射为 acceptance.objective=null，使用 requirements 与 gates 验收，不编造分数。无地图时将 Map 行替换为 Task: <真实任务文件的项目相对路径>。

新简报按任务与证据以 `ready-for-onboard` 生成，仅表示可以据此起草合同；`draft` 保留给已有简报重新讨论的状态，用于待修订的简报。把 TODO 替换为实际内容或“未知 + 原因”。`brief-check` 只看结构和字段是否存在，不判断内容是否合理。

---

# 任务名称

## Source
Map: .opc/research/topics/<topic>/research-map.md
Status: ready-for-onboard

TODO：地图中对应的方向 ID/名称、依赖；用户任务来源、会话日期或文档依据及所采用的假设。

## Question and use

TODO：要回答的问题、为何优先、结论给谁/哪个决策用。

## Goal
Goal: TODO 一句话目标（暂定也要写）
Done when: TODO 达到什么状态算这个任务做完
Direction: TODO 建议的大致路线；未定时写“未定”及原因

## Evidence

TODO：索引 `evidence/` 中的文件，一句话写各自支持的判断；列出关键缺口。区分已读源码、已执行结果和推测。

## Scope and deliverables
In: TODO 暂定包含
Out: TODO 暂定排除

- D1: TODO 交付物 | 形式（参数表及来源/机制说明/可重放案例…） | 适用范围
- R1: TODO 验收条件 | verification=automated | evaluator=已有/待建/未知

Objective: TODO 指标名 minimize|maximize，或 none: 原因
Adjust if: TODO 什么发现会缩小、扩大或取消目标

交付物要能辨认，不是“研究报告”四个字。`verification=automated` 表示能由评价器或命令自动判定，`review` 表示需要人或独立审核判定。阈值未知时在条件里写确定方法，不臆造数值。

## Open decisions

TODO：留给 onboard 确定的事项（如基线、评价器是否需要新建）；默认 token 无上限、Task 时间额度两小时，仅记录用户明确限制；已知的引擎能力缺口。确实没有时写“无”及依据。