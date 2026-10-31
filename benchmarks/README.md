# ArcHa 测试项目

S0 确定三个模块题与一个独立端到端课题。各题的 Markdown `TASK.md` 可作为 `$archa-map` 输入；原始材料已本地封装，实际自检结果见 [准备报告](../docs/reports/benchmark-preparation-20261031/README.md)。正式考试待 S1–S5 必要改造完成。

| 题目 | 目标 | 题内材料 |
| --- | --- | --- |
| [开发](deepstack-development/README.md) | 实现通信代价模型 | 公开接口、缺失实现、样例；无目标源码答案 |
| [调优](ramulator2-optimization/README.md) | DDR4 Generic/FRFCFS 等价加速 | 固定 Ramulator 源码、构建依赖、负载生成器 |
| [探索](deepstack-exploration/README.md) | 解释 3D 存储建模及必要上下游 | 固定 DeepStack 原始发行版和论文，题目范围限定于模块 |
| [独立端到端](deepstack-end-to-end/README.md) | 独立解释完整建模架构与过程 | 独立完整原始发行版和论文，不继承模块题成果 |

另保留 [DMA 小型回归](dma-backpressure/README.md)、[DeepStack 来源登记](deepstack/README.md)；[旧 bank 调优方案](deepstack-optimization/README.md)已撤回。

## 四题考试边界

四题没有先修依赖，各用独立上下文/工作区，不分享代码、结论、实验或提示。完整参考工程保留 `/root/DeepStack` 和 `/root/ramulator2`，不向 Worker 开放；不必搬迁到 external。源码来自固定 commit 的 git archive，排除外部工作树未提交改动，保留原许可。

Worker 只取得本题 `runs/<label>/project` 及明确运行依赖，不取得题目根目录、examiner 或本仓库研究笔记。当前准备工程为 `runs/prepared/project`；其上一层的 manifest 记录来源与逐文件 SHA-256。源码、运行时、原始日志和独立 Git 工程均忽略，不向主仓库提交多份上游源码。

本地执行使用 `tools/isolate.py`，已核对跨题/参考库/验收器读取与外部写入、网络限制；详细边界见 [环境说明](ENVIRONMENT.md)。正式 Worker 的读文件、shell 等工具仍须由 S2 接入同一边界，不能以 cwd 或普通 workspace-write 替代读取隔离。模型 API 由外层编排器负责，不在题内开网络。

## 入口与记录

- `TASK.md`：可见需求；`starter/`：可见接口/样例/公开交付口径。
- `examiner/`：操作者验收，不能给 Worker；`examiner/private/`：本地冻结基线/原件。
- `runs/<label>/project`：独立工程；`manifest.json`：版本和输入摘要；完整执行/验收原件留在本地。
- `docs/reports/benchmark-preparation-20261031`：本次必要自检摘要；正式考试再建立自己的结果索引。

结果默认短索引，连接单项说明与 CSV/JSON/JSONL trace，不强制多层报告。运行事实优先索引框架已有账本/日志。正式开考补充框架提交、模型、预算、revision/Run、selected commit 与外置验收结果；环境可运行、候选通过和框架自报完成分别记录。

复建、隔离、构建和外置核对命令见 [ENVIRONMENT.md](ENVIRONMENT.md)。
