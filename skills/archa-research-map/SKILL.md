---
name: archa-research-map
description: 初始化当前项目的 ArcHa 本地运行代码，与用户讨论研究方向，生成 .opc/research/research-map.md、研究任务清单及占位目录。用于形成或修订研究地图；具体任务的背景调查和简报交给 archa-task-brief。
---

# 研究地图

## 初始化与恢复

目标项目默认当前工作目录，用户指定路径时以指定路径为准。读取项目约定和已有研究材料。首次调用先运行本技能目录的 `scripts/initialize.py`：

```bash
python3 /absolute/path/to/archa-research-map/scripts/initialize.py --project /absolute/project
```

脚本只部署 `.opc/runtime/` 运行代码和 `.opc/archa.py` 入口，合同骨架留到 onboard 时生成。打包文件由脚本中的 `RUNTIME_FILES` 明确列出，包含 CLI、引擎、worker、内置策略和起草资源，不复制仓库文档、测试、示例或开发工具。已有 `.opc/` 保留其合同与执行状态；重复调用校验已有快照，不自动升级。快照修改导致校验失败时保留用户修改并报告差异，不擅自重装。初始化成功只证明文件就位。

已有 `.opc/research/research-map.md` 时恢复地图、当前焦点、未决问题和任务材料。已有其他位置的研究地图时先引用来源，保留历史路径与证据，不静默迁移冻结材料。

## 共同形成方向

从“研究得到什么、谁用结论、为何值得做”展开。调查必要源码和原始来源，再解释具体用途、依据与代价；把已读源码、已执行结果和推测分开。先检验一个关键前提，给出可删、推迟或缩小的工作及理由。环境有 winson 时可借用其讨论方式，本技能自身可独立完成讨论。

与用户选择地图的表达方式：链路、问题树、机制关系或其他适合的结构。正文不套合同模板；暂不要求数值目标、预算或实验清单。agent 提出有依据的选项和建议，用户决定重要取舍。每轮聚焦一个可回答的问题，保存真实回答，沉默不算同意。

讨论中将目的、分歧和下一问题写入 `.opc/research/discussion.md`；地图可标为草稿。用户认可方向与组织方式后，按 [产物约定](references/research-layout.md) 完成 `research-map.md`，为每个研究方向创建稳定 ID 的任务占位目录和 `task.md`。清单是简报准备进度，不是实验进度。

完成条件：地图说明用途与方向关系，清单中的每项都有可打开的占位文件，未决事项已记录。修订地图时不删除旧任务或证据。

## 交给下一阶段

在地图末尾和回复中给出可复制提示词，替换为实际绝对路径：

```text
$archa-task-brief /absolute/project/.opc/research/research-map.md
```

说明推荐先讨论哪个任务及原因；本次结束于地图交付，不自动进入第二阶段、onboard 或实验。