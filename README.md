<p align="center"><img src="docs/assets/archa-aha-orange.svg" width="160" alt="ArcHa 啊哈！橙色 Logo" /></p>

# ArcHa · Architecture Harness

ArcHa 用持续专题组织研究：人定义目标，Expert 消化证据并选择下一问，Executor 核查资料或完成最小实验。目标、当前认知状态与逐轮探针/结果保存在目标工程的 `.archa/topics/<topic>/`，停止后可以修改并继续。

Python 发行包为 `archa-opc`，命令为 `opc`，要求 Python 3.10+。Worker 通过命令数组接入外部 CLI 或脚本；默认 Codex 配置需要本机已有可用的 Codex CLI 和授权。

```bash
pip install -e .
opc init -p /path/to/project --topic investigation --goal "明确目标、范围、环境入口与完成判据" --max-rounds 3
# 检查并按需要修改目标工程 .archa/workers.json
opc check -p /path/to/project --topic investigation
opc run -p /path/to/project --topic investigation
opc status -p /path/to/project --topic investigation
```

`step` 只执行一次角色调用；`stop` 等待当前调用及后代进程停止。停止后可编辑 `GOAL.md`、`STATE.md` 和未执行的 `probe.md`，再用 `resume` 继续。`resume --add-rounds 2` 增加累计轮数上限；已完成专题不会自动重开。完整命令、退出码与配置说明见 [引擎说明](opc/README.md)。

同一工程最多一个执行者。调用失败立即停止并保留日志；恢复复用已提交成果，未提交调用可能重跑，工程修改不会自动撤销。预算耗尽时 Expert 仍消化最后结果。研究完成由 Expert 根据目标和证据判断，不触发合并或发布。

使用两个流程技能：

- `/archa-discuss`：通过多轮讨论澄清需求、比较探索方向并形成专题目标，并确认环境就绪与反馈回路；目标、必要准备均就绪且已有执行授权时交接，否则留在讨论阶段。
- `/archa-run`：按已明确且执行准备就绪的目标启动或继续探索与优化，也负责停止、查看进展和按需离线报告。技术未知留在循环中解决；目标或范围改变时回到讨论。

两个入口共用 GOAL.md、STATE.md 与逐轮材料，不要求预拆方向或另写交接文档。安装到指定技能目录：

```bash
python tools/install_research_skills.py --destination /path/to/skills
```

安装器只安装这两个技能，并将指定目录中的旧四技能移到相邻的 `skill-backups`，不保留旧入口或别名。

目标项目经 `archa-discuss/scripts/initialize.py --project PROJECT` 获得 `.archa/archa.py` 和固定快照 runtime；以后通过 `python PROJECT/.archa/archa.py ...` 调用，不依赖全局安装。既有项目保留固定版本；仅在停止后显式使用 `--update` 升级运行时并备份旧快照。升级保留 `.archa/workers.json`；自定义 Codex 命令若含 `-o {output_file}`，需显式移除该参数，避免最终聊天摘要覆盖 Worker 已写的探针、结果或状态文件。

工作台显示专题状态、Expert/Executor/收尾日志与材料，默认只读；加 `--control` 开启停止、继续和追加轮数：

```bash
pip install -e '.[observer]'
npm --prefix web ci
npm --prefix web run build
python -m opc.observer --project /path/to/project --control
```

打开 `http://127.0.0.1:8765`。`python -m opc.observer --demo` 使用临时离线演示材料。工作台只绑定本机地址，材料阅读不会执行原始 HTML。

开发验证：`python -m pytest -q` 收集核心与工具测试；`npm --prefix web run build` 完成类型检查和生产构建。安装 Playwright/Chromium 后运行 `tools/observer_browser_smoke.py` 与 `tools/workbench_control_smoke.py`，验证真实浏览器和后端流程。跨平台边界见 [说明](docs/cross-platform.md)。

实现及验收依据：[开发方案](archa-refactor-plan.md)、[专题工作区 ADR](docs/adr/0001-topic-workspace.md)、[术语表](GLOSSARY.md)。旧 `.opc/` 运行格式已退役；旧研究数据、规格和验证记录作为历史保留，不迁移或自动继续执行。
