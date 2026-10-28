# 研究材料约定

```text
.opc/
  archa.py                         项目内 CLI；python3 .opc/archa.py --help
  runtime/                         ArcHa 代码、许可证、来源及逐文件摘要
  research/
    research-map.md                自由结构地图 + 唯一任务清单
    discussion.md                  用户决定、未决问题、当前焦点和返回点
    tasks/
      r01-input-flow/
        task.md                    第一阶段的方向占位
        task-brief.md              第二阶段用户确认大纲后产生
        evidence/                  第二阶段产生，保存证据和有限结论
```

`research/tasks/` 是研究讨论目录；`.opc/tasks/` 是执行合同目录，两者通过简报 Source 关联，不混用。

需要持续研究成果时，task 合同的可选 `results_path` 指向稳定 Markdown 入口。项目已有 workloads/specs/index 均保留原位置，入口用相对链接组织计划、批次、累计结论和审核。`opc results` 与引擎共用登记逻辑；运行事实以 ledger 为准，README 自动区只做投影，人工区保存摘要、条件与下一步。具体目录由项目确定，不把领域路径写进 runtime。

## 地图末尾的任务清单

地图正文自由组织，附上下面这类清单和接续提示词。路径相对地图文件。每个方向至少一个任务；稳定 ID 不因排序或标题变化而更换。拆分任务时给新 ID，保留旧条目的去向。

```markdown
## 研究任务 to-do

勾选仅表示简报已确认可交给 onboard 起草，不代表研究已完成或允许执行。

- [ ] R01 | [理解输入消费链](tasks/r01-input-flow/task.md) | status=todo | depends=none
- [ ] R02 | [确定调度研究范围](tasks/r02-scheduling/task.md) | status=parked | depends=R01（需要实际输入消费位置）

## 下一步

推荐 R01，因为 R02 需要知道实际输入消费位置。

`$archa-task /absolute/project/.opc/research/research-map.md`
```

状态只有四种：

- `todo`：未开始。
- `active`：第二阶段正在调研、澄清或等待用户确认 brief 大纲。
- `ready-for-onboard`：简报已确认，可交给 onboard 起草；只有这一项勾选。
- `parked`：阻塞、暂缓或取消，在 `depends` 或 `task.md` 写明原因和重开条件。

状态由主 agent 更新，sub-agent 只交调查结果。

`task.md` 保持短小：稳定 ID 与方向名、回到地图的相对链接、问题与预期用途、暂定包含/排除、依赖和当前缺口。尚未知的内容写原因，不填写虚构参数。

## 修订

地图记录日期和重大方向变更。新证据推翻前提时，链接证据说明影响，把受影响任务取消勾选改回 `active` 或 `parked`，若已有简报，将其标为 `Status: draft` 并记录修订原因；正文修订由 archa-task 展示新大纲并经用户确认后生成；保留历史版本和证据。执行中的合同变更交由独立 revision/run 流程处理。
