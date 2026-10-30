# DeepStack 测试项目登记

状态：**registered / task_pending**。已登记 DeepStack 主线和固定版本；最终研究方向已确定为底层建模探索，执行合同待讨论。测试方法前置设计，正式测试在 ArcHa 改造完成后开展，见 [阶段规划](../../docs/architecture-and-task-policies/ArcHa_Phased_Development_Plan.md)。本次未安装或运行，现有部署可用性未核验；不将论文复现版自动作为任务。

| 字段 | 值 |
| --- | --- |
| 上游 | https://github.com/tile-ai/DeepStack |
| 版本线 | main |
| 固定 commit | `17e21bf54115e11b9e7c6edc0b2d1723d25d022b` |
| 机器可读来源 | [source.json](source.json) |
| 任务 | [TASK.md](TASK.md)，建模探索方向已定，执行合同待讨论 |

版本来自本机 `/root/DeepStack` 的 Git HEAD 和已提交 README；本地工作树有未提交改动，**不把这些改动算作固定基线，也不复制当前工作树**。后续从上游取得上述 commit 的干净 checkout，保存实际源码 SHA-256/清单和环境。若取不到固定提交，应停止准备，不改用浮动 main。

上游定位为 GPU / 3D-stacked LLM inference 分析建模，已提交 README 说明使用 CPython 3.11、x86-64 Linux，建模在 CPU 运行。上游主线与 ae 的论文复现快照有不同用途；具体环境、依赖和许可应以固定提交的 README/LICENSING 为准，当前登记不声称环境可运行。

后续先明确研究范围、允许读取/修改的材料、输入与环境、用户指定的资源边界及结论核对/完成条件，再准备 starter、examiner 和 runs。具体任务确定前不创建实现、验收程序或结果。目录使用 [公共约定](../README.md)，未来源码只放独立运行工程，保留上游许可与 NOTICE。
