# 项目需求与追踪

> 起草者：Ge；生成时点：用户材料导入后，随已确认方向或新证据修订。
> 来源权威：用户 MRD/SPEC、已确认决定及明确版本的已有规范。
> 关联 JSON：任务修订 `task.json.requirements`、`source_requirements`、`must_haves`。
> 保存位置：`.opc/context/REQUIREMENTS.md`。Ge 提取成表，用户只需补无法从材料确定的关键决定。

## 当前需求

每项采用稳定 `requirement_id`。ID 不因改写措辞而更换；含义改变须显式记录修订。

| requirement_id | statement | current_state | target_state | category / priority |
| --- | --- | --- | --- | --- |
| <req-example-01> | <要求什么行为> | <当前状态或明确未知> | <目标行为与条件> | <functional / must> |

| requirement_id | success_criterion | negative_constraints | verification_mode | source_refs |
| --- | --- | --- | --- | --- |
| <req-example-01> | <阈值、输入、边界与通过条件> | <禁止改变的行为/评价器等> | <automated> | <URI + sha256 + locator> |

`category` 取 functional / performance / research / reproducibility / integration。
`priority` 取 must / should；进入当前 TaskSpec 的两类需求都必须记录验证结果，should 不表示可隐式漏验。
`verification_mode` 取 automated / independent_review / human_judgment；“自动”仍需证据与独立审核。

## 需求到证据

| requirement_id | task_id / revision | observable check_id | artifact_id / logical_path | key-link link_id | review / coverage |
| --- | --- | --- | --- | --- | --- |
| <req-example-01> | <任务 / 修订> | <可观察行为检查> | <产物与用途> | <生产者→消费者的实际连接检查，或无> | <尚未提交> |

每项需求至少对应一个 observable 或 key-link；产物存在不等于需求达成。
多个任务可共同支撑项目需求，但每个任务只对本修订范围负责；项目级完成需汇集适用且未失效的接纳证据。
下游依赖必须绑定已接纳 submission 与 manifest 摘要，不把本表“完成”当依赖凭证。

## 延后与排除

| 条目 | 延后 / 排除理由 | 再考虑的触发条件 |
| --- | --- | --- |
| <内容> | <用户决定 / 预算 / 前置条件> | <条件或不再考虑> |

延后项保留在这里或 `context.deferred`，不放进当前任务完成分母；不能为让审核通过而事后移出当前需求。
未解决的目标含糊点记录到 `open_decisions`；需要实验求证的未知记录到 `research_unknowns`。
来源或决定变化由 Ge 形成新 TaskSpec 修订，并显式说明对已有计划与审核证据的影响。
