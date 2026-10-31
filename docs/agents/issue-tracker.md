# Issue tracker: Local Markdown

本仓库的事项和规格保存在 `.scratch/` 下的 Markdown 文件中。

## 文件约定

- 每个功能使用一个目录：`.scratch/<feature-slug>/`。
- 规格保存在 `spec.md`。
- 实现事项各占一个文件：`issues/<NN>-<slug>.md`，从 `01` 开始编号。
- 每个事项文件顶部附近使用 `Status:` 记录 triage 状态，具体值见 [triage-labels.md](triage-labels.md)。
- 评论和讨论追加到文件底部的 `## Comments` 下。

## 技能操作映射

- “publish to the issue tracker”：在对应功能目录中创建规格或事项文件，必要时创建目录。
- “fetch the relevant ticket”：读取用户指定路径或编号对应的事项文件。

## Wayfinding 操作

供 `/wayfinder` 使用：

- 地图：`.scratch/<effort>/map.md`，包含 Notes、Decisions-so-far 和 Fog。
- 子事项：`.scratch/<effort>/issues/<NN>-<slug>.md`，从 `01` 开始编号，正文记录待解决的问题。
- 类型：使用 `Type:`，值为 research、prototype、grilling 或 task。
- 执行状态：使用 `Status: claimed` 或 `Status: resolved`。
- 依赖：顶部附近使用 `Blocked by: NN, NN`。所列事项全部 resolved 后，当前事项解除阻塞。
- 下一项：按编号选择尚未解决、无阻塞且尚未认领的事项。
- 认领：开始工作前写入 `Status: claimed`。
- 解决：在 `## Answer` 下追加答案，设置 `Status: resolved`，并在地图的 Decisions-so-far 中追加摘要和文件链接。
