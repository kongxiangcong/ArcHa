# 多研究专题与目录式技能入口：实施 tickets

需求：2026-10-29 用户确认的开发需求（源码检查基线 ae25f8c）。实施基线：拉取 origin/main 后的 8b70578。

- [x] T1：三个技能、引用文档与 README 改为具体任务目录入口；明确每次 map 新专题、同次讨论复用、旧布局及错误输入规则。
- [x] T2：集中实现专题创建与目录合同接续辅助能力；DECISIONS 复用路径身份，摘要变化保留 task ID，显式 onboard task ID，保留 runtime 与历史。
- [x] T3：离线验收双专题 R01、重复接续与修订、命名冲突、旧布局、错误路径、运行历史保留及技能包一致性；运行相关回归并报告部署边界。

不新增路由数据库或当前专题，不迁移旧材料，不安装全局技能或更新未指定的外部项目。辅助脚本随技能安装，避免为目录解析强制升级旧 runtime。

## 完成与验证记录

2026-10-29：T1–T3 已按顺序完成。main 已由 f86d14e 快进至 origin/main 的 8b70578；实现变更留在当前工作区，未 push。

修改清单：

- 三个 SKILL、研究布局、简报/证据/消费链 references、README：目录式入口、新专题及旧布局规则、绝对目录交接和缺失输入行为。
- `skills/archa-map/scripts/research.py`：集中 create/resolve/record；重名序号、导航、稳定目录身份、DECISIONS 追加交接、冲突与歧义拒绝、简报变化返还准备、首次骨架及身份预留。没有新增映射文件、数据库或当前专题。
- `opc/scaffold/onboard.py` 与 ONBOARDING：worker 明确消费传入的 task ID；准备审核候选绑定简报路径与摘要，简报变化不复用旧候选。
- `tools/tests/test_research_skills.py`、`opc/tests/test_accounting_recovery.py`：双专题 R01 的真实 onboard（离线 worker）、恢复、修订、冻结历史和累计用量、旧目录、外置任务、冲突/歧义、无写入错误提示、带空格/相对路径及安装包一致性。
- [usage.md](usage.md)：用法、辅助脚本边界与固定对话样例。

执行过的验证：

- 隔离环境 `/tmp/archa-topics-venv`，安装仓库声明的 dev/observer 依赖。
- 全仓 `python -m pytest -q --tb=short`：359 passed、5 skipped、12 subtests passed。沙箱内观察器测试阻塞，终止该测试进程后在同一环境沙箱外完成全部离线回归。1 条既有 Starlette/AnyIO 弃用警告。
- 最后补充显式 `../` 相对目录及冻结正式 run 历史后，定向执行研究技能与接入记账测试：28 passed、1 skipped。
- `git diff --check`、scaffold 与技能脚本编译检查通过。
- 临时项目中检查实际生成和恢复的 task ID、revision 与合同路径；r0002 后 r0001 字节保持不变、正式 run 历史保留、准备 run 身份与累计 token 保留。新建专题及重复初始化不改原 runtime、合同、ledger、旧地图/讨论/任务。
- 临时安装包验证三个技能正文与源码逐字一致，辅助脚本随包迁移并能创建专题；已有安装备份与 pinned runtime 回归通过。

部署与未验证边界：

- 仓库实现：完成，当前工作区可审阅；未提交或推送本次修改。
- 全局技能安装：未执行；仅在临时目录安装验证。
- 外部项目 runtime：未更新；默认保持旧快照，不把源码完成视作部署完成。onboard 提示与候选摘要检查需要显式更新 runtime 才生效。
- 无真实模型、设备实验或 Windows 实机验证；5 项平台专用检查跳过。固定对话样例是协议与脚本检查，并非真实模型对话回放。旧式自由文本交接需要 agent 核对明确来源后补记，不自动猜测绑定。
