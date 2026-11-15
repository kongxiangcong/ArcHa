---
name: archa-log
description: 按需将专题目标、当前认知和逐轮结果整理为可追溯的研究进展报告。
---

1. 确定工程与专题。若执行仍活跃，先向用户说明报告需要一致的已提交材料；按已有停止授权调用 stop 并确认结束，否则待本次调用结束后再生成。
2. 运行 `python SKILL_DIR/scripts/log.py -p PROJECT --topic SLUG`，或本地 `.archa/archa.py report -p PROJECT --topic SLUG`。运行时必须已部署；命令显式报错时按实际错误处理。
3. 阅读生成的 `.archa/topics/SLUG/PROGRESS_LOG.md`，向用户概述目标、证据、当前解释、适用条件与未解问题并链接报告。报告默认离线整理，不调用模型；需要进一步叙事润色时在这份衍生报告内完成，并保留来源引用和事实/解释/假设的区分。

报告不更改 GOAL.md、STATE.md 或轮次结果，不成为第二份认知账本。原件与脚本直接引用；当前 STATE.md 明确标为当前理解，不伪装为历史轮次快照。每轮探索不自动生成报告。
