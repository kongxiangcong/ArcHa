# 多专题与目录式接续

```text
$archa-map 探讨 DMA 调度优化的研究方向
$archa-task /project/.opc/research/topics/dma-scheduling/tasks/r01-baseline/
$archa-loop /project/.opc/research/topics/dma-scheduling/tasks/r01-baseline/
```

后两项也接受相对当前工作目录的明确目录，含空格时加引号。map 每次显式调用创建新专题；同名追加序号。继续讨论旧专题直接给原目录和修改需求，不重新调用 map。索引只有名称、范围及地图链接。

## 内部接续

技能包内 `archa-map/scripts/research.py` 集中处理 create、resolve 和 record；无需为目录入口升级已有 runtime。首次准备由 resolve --prepare 依据目录生成可读 ID，并在现有 DECISIONS.md 预留身份。全新项目先调用已有 CLI init 创建该 ID 的骨架；已有项目不重新初始化。失败重试仍用预留身份。

onboard 始终显式传 --task 与 --brief。核对实际合同后 record 追加简报相对路径、摘要、task ID、revision 和合同路径。旧式 prose 交接由 agent 核对后补记；不推断、不改 ID。record 不是语义审核，调用者必须先完成合同核对。摘要变化保留 ID，loop 返回对应目录的 archa-task 接续；新 revision 沿用累计账本。

辅助脚本可随技能包迁移；只有初始化全新合同需要已有 `.opc/archa.py`。本次 onboard 新提示与摘要复用检查属于 runtime 改进，旧 runtime 保持固定版本；如需要这些改进，需单独显式更新 runtime。旧版仍由技能显式传 ID 并核对合同；旧版准备审核候选是否消费新简报须人工核对，不以全局技能安装代替 runtime 更新。

## 固定对话验收样例

| 输入 / 后续消息 | 期望行为 | 本次检查 |
| --- | --- | --- |
| `$archa-task` 或 `$archa-loop` | 一次简短提示提供具体任务目录；不准备、不运行 | 对照两个 SKILL 入口规则；脚本无路径测试通过 |
| `$archa-task /project`、专题根、tasks 集合 | 提示具体任务目录，不自动选择 R01 | 脚本无写入测试通过 |
| `$archa-loop .../task-brief.md` | 提示所属任务目录，CLI --brief 仍可用 | 文件输入回归通过 |
| `$archa-map DMA 调度研究`，工具返回 dma-scheduling-2 | 回复与导航使用返回路径 | 重名专题及导航测试通过 |
| 同次调用补充“还要考虑排队公平性” | 写入本次 discussion，沿用已保存专题路径，不再 create | 固定延续路径测试、SKILL 规则核对 |
| 新的显式 `$archa-map 量化研究` | 新建专题，不恢复最近地图 | 双专题离线测试通过 |
| 提供原专题目录“修改研究范围” | 原位修订，保留任务与证据，不创建专题 | SKILL 历史保留规则核对 |

这些固定样例核对技能协议和确定性脚本行为，并非真实模型对话回放；模型是否每次遵守工具调用约定未做在线验证。
