---
name: archa-task
description: 澄清专题目标、调整待解问题或检查 Expert/Executor Worker 配置。
---

1. 定位目标工程和专题，阅读 GOAL.md、STATE.md 与当前待执行探针。尚未建立专题时使用 archa-map 的部署与初始化入口。
2. 修改前查询本地 `status`；若在运行，调用 `stop` 并等待确认结束。与用户明确目标范围、环境入口、完成判据和当前一个关键问题，直接更新 GOAL.md 与 STATE.md 问题队列。保留状态头和已授权预算，保留已完成轮次；实质换题另建专题。
3. 检查 `.archa/workers.json`：Expert 与 Executor 分别使用明确 preset 或 argv 命令；仅配置实际使用的模板参数。用本地入口 `check -p PROJECT --topic SLUG` 只读检查配置，并确认命令可用、输出路径与权限符合目标工程。Expert 使用 file 输出；Executor 可显式 stdout 输出。不得将真实模型调用作为配置检查。
4. 汇报已澄清目标与剩余缺口。用户已授权继续时直接调用本地 `resume`；只讨论目标时不启动探索。

配置字段、模板与命令以部署的运行时 `--help` 和 `.archa/workers.json` 为准；无需冻结契约或独立审核。
