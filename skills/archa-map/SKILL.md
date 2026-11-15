---
name: archa-map
description: 初始化研究专题或为实质不同的研究目标建立独立专题；部署工程内 ArcHa 运行时。
---

1. 确定目标工程与专题 slug；已有专题继续沿用其目录，实质换题才新建。先阅读已有目标与状态。
2. 运行本技能 `scripts/initialize.py --project PROJECT`，部署 `.archa/archa.py` 与运行时。升级仅在停止后用 `--update`，保留原快照备份。旧 `.opc/` 数据保留原位。
3. 用 `python PROJECT/.archa/archa.py init -p PROJECT --topic SLUG --goal "明确目标" --max-rounds N` 创建专题。已有目标、状态与 Worker 配置不会覆盖；目标不明确时先澄清范围、环境入口与完成判据，再写入 GOAL.md。
4. 告知专题路径及当前待解问题。用户已要求启动且目标明确时，检查 Worker 配置后直接运行本地 `run`，不要求依次调用其他技能。预算使用用户授权值。

需要定位权威材料或了解人工修改边界时，读 [研究布局](references/research-layout.md)。
