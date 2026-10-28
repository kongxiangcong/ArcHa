# 简报如何被 ArcHa 消费

核对目标项目 `.opc/runtime/opc/` 的实际实现，版本不一致时报告差异。

`onboard --brief` 先跑 `brief-check`；若项目只有 runtime 和入口，就在这时生成合同骨架，再把简报正文和来源摘要交给起草 worker。worker 据此起草具体合同，未定项写入 `.opc/README.md` 的 Open items，保持执行关闭。runtime、地图、简报和 evidence 是只读输入。所以简报要说清楚的是“做什么、交付什么、怎样算做成”，“怎么在引擎里跑”交给起草阶段。

task-brief 技能生成简报后自动调用上述流程并核对产出；把简报路径及摘要与实际 task/revision 的对应关系记录在 `.opc/context/DECISIONS.md`。用户随后用 `archa-loop <task-brief-path>` 启动执行准备和迭代，无需手动选择引擎任务 ID。

简报字段在合同里的落点（供判断写到什么粒度）：

- `Goal:` → `task.goal`；`Direction:` → `task.direction`；Question and use、Done when 和交付物 `D*` → `.opc/context/REQUIREMENTS.md`。
- `- R*:` → `task.requirements[]`（`verification` 原样对应；`evaluator=待建/未知` 成为 Open item）。
- `Objective:` → `acceptance.objective`；数值必须由真实评价器产生，`none` 映射 objective=null，完成条件使用 requirements、冻结 gates 和必要 review；不构造伪分数。
- In/Out → 起草时细化成可改/冻结路径和基线 ref。
- Open decisions → `.opc/README.md` Open items，token/时间默认无上限，仅用户明确给出时写入 .opc/local/workers.json 的 budget，不为预算提问。

当前引擎不原生支持：没有源码补丁的纯取证、每轮独立研究审核、跨任务依赖调度。任务需要这些时在 Open decisions 写明，不要编造优化分数来套用。

正常 loop 使用 run --deliver，读取 delivery.complete 后交付；失败按已登记 promotion 的 findings 自主修复。默认准备不要求独立 reviewer，合同 preparation_review=true 才审核。终验后不自动 apply；纯验收标准修订使用新 revision 和显式 --source-run/--standards-confirmation。
