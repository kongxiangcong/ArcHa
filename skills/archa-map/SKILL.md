---
name: archa-map
description: 初始化当前项目的 ArcHa 本地运行代码，与用户讨论研究方向，每次显式调用创建 .opc/research/topics/<topic>/ 下的新专题、研究任务清单及占位目录。用于形成新研究地图；具体任务的背景调查和简报交给 archa-task。
---

# 研究地图

## 初始化与恢复

必需输入新研究需求。缺少需求时简短提示补充研究目标，不创建空专题。目标项目默认当前工作目录，用户指定路径时以指定路径为准。读取项目约定和已有研究材料。首次调用先运行本技能目录的 `scripts/initialize.py`：

```bash
python3 /absolute/path/to/archa-map/scripts/initialize.py --project /absolute/project
```

脚本只部署 `.opc/runtime/` 运行代码和 `.opc/archa.py` 入口，合同骨架留到 onboard 时生成。打包文件由脚本中的 `RUNTIME_FILES` 明确列出，包含 CLI、引擎、worker、内置策略和起草资源，不复制仓库文档、测试、示例或开发工具。已有 `.opc/` 保留其合同与执行状态；重复调用校验已有快照，不自动升级。快照修改导致校验失败时保留用户修改并报告差异，不擅自重装。初始化成功只证明文件就位。

每次显式调用创建新专题。依据需求生成简短可读的英文 slug，初始化后运行：

```bash
python3 /absolute/path/to/archa-map/scripts/research.py create --project /absolute/project --name dma-scheduling --title "DMA 调度" --scope "调度优化研究"
```

使用返回的实际 topic 路径（重名自动追加序号），本次会话、补充消息、上下文恢复和工具重试始终沿用该路径；创建成功后不再次调用 create。保存该路径到本次讨论上下文。标题调整不改目录。继续旧专题时用户直接提供原目录及修改需求，不再次调用 archa-map。旧布局地图与外置材料保留原位置，可在 index.md 导航中引用。index 只含名称、范围和地图链接，不承担任务路由或状态管理。

用户要求升级 runtime 时，停止控制器后使用同一脚本的 `--update`；它校验旧快照、复用控制器锁，在 `.opc/local/runtime-backups/` 保留旧 runtime，再替换运行代码。合同、ledger、预算与研究原件保留。默认恢复仍固定旧版本；修改过的 runtime 校验失败时先保留并处理本地差异。

## 共同形成方向

从“研究得到什么、谁用结论、为何值得做”展开。调查必要源码和原始来源，再解释具体用途、依据与代价；把已读源码、已执行结果和推测分开。先检验一个关键前提，给出可删、推迟或缩小的工作及理由。环境有 winson 时可借用其讨论方式，本技能自身可独立完成讨论。

与用户选择地图的表达方式：链路、问题树、机制关系或其他适合的结构。正文不套合同模板；暂不要求数值目标、预算或实验清单。agent 根据用户目标与证据选择合理方案，记录假设并继续，不以提问或地图确认作为暂停关卡。用户明确决定优先，不把推断写成用户确认。

讨论中将目的、分歧和下一问题写入 `<本次专题>/discussion.md`；地图可标为草稿。根据已有需求与证据自主确定方向与组织方式后，按 [产物约定](references/research-layout.md) 完成 `research-map.md`，为每个研究方向创建稳定 ID 的任务占位目录和 `task.md`。清单是简报准备进度，不是实验进度。

完成条件：地图说明用途与方向关系，清单中的每项都有可打开的占位文件，未决事项已记录。修订地图时不删除旧任务或证据。

## 交给下一阶段

在地图末尾和回复中给出可复制提示词，替换为实际绝对路径：

```text
$archa-task /absolute/project/.opc/research/topics/dma-scheduling/tasks/r01-baseline/
```

说明新专题实际绝对路径、推荐先讨论哪个任务及原因；路径含空格时加双引号；本次结束于地图交付，不自动进入第二阶段、onboard 或实验。

## 默认预算

预算与模型统一配置在 `.opc/local/workers.json` 的 `budget` 对象：`max_tokens`、`max_wall_seconds` 默认 `null`（无上限），可分别设置。仅用户明确给出相应上限时写入数值；保留已有明确配置，不从模板、历史实验或 agent 估算生成限制，不为预算停下来提问。正常推进已授权工作，持续记录实际用量；无上限时缺失计量只标为 unknown，不阻塞执行。显式 token 上限要求可靠累计 token，显式时间上限要求可靠累计时间；无法自主恢复必要计量时报告实际阻塞。保留用户 pause/stop、真实外部权限和冻结验收边界。
