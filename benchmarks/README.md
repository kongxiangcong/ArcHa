# ArcHa 测试项目

本目录收纳用于验证 ArcHa 的项目材料与实验记录。框架语义回归仍在 `opc/tests`、`tools/tests`；项目材料自检可以接入该回归，但不替代真实模型闭环。

| 项目 | 用途 | 当前状态 |
| --- | --- | --- |
| [dma-backpressure](dma-backpressure/README.md) | 小型、无第三方依赖的工程闭环冒烟 | 材料就绪；本次目录整理未运行模型 |
| [deepstack](deepstack/README.md) | 真实项目研究测试入口 | 已登记主线固定版本；任务与验收待定，禁止据此启动 |

## 公共目录约定

```text
<project>/
├── README.md                 # 用途、运行方法、完成条件和状态
├── TASK.md                   # worker 可见的任务；待定项目明确标记
├── starter/                  # worker 可见初始材料，或固定源码来源说明
├── examiner/                 # 操作者持有的外置验收及材料自检
├── reports/<date>-<label>/   # report.md、summary.json 和必要的可审阅证据
└── runs/<date>-<label>-<NN>/ # 完整本地原件，Git 忽略
    ├── manifest.json        # 输入摘要、版本、配置与实际命令
    ├── project/             # 独立 Git 工程，含 .opc 与账本
    ├── workspaces/          # project 外的 ArcHa 工作树
    ├── acceptance/          # 操作者冻结的验收输入、候选导出和完整结果
    └── logs/                # 启动日志；框架已有日志通过路径索引
```

只在实际运行时创建 runs 子目录；只在有结果可记录时创建带日期的 reports。任务待定时，不伪造验收程序、初始工程或实验报告。外部大项目以 URL 和不可变 commit 登记，源码在运行时取得，不将整个上游、依赖或模型库复制进本仓库。

## 运行与证据

1. 从固定输入创建全新的独立 Git 工程。只把 TASK.md 和 starter 中的 worker 可见材料带入 project；框架接入、模型、预算及冻结合同写入本次 manifest。
2. 工作树根绑定到同次运行的 workspaces，与 project 分离。通过项目目录执行 `archa-map → archa-task → archa-loop`，沿用框架已有 task/run 身份、账本、promote 与日志。
3. examiner、acceptance、其他候选及 reports 不进入 worker 的工程、上下文或可读取范围。**同仓库的兄弟目录不是访问控制**：需由运行环境/账户的文件读取权限保证隔离；普通 workspace-write 往往只约束写入。不能保证时，在独立容器或账户中运行，只挂载 worker 工程和必要 runtime，验收留在操作者环境；尚未配置隔离时不得声称盲验。
4. 操作者对明确的 selected commit 导出候选，执行外置验收，保留原件和命令。该验收独立于框架的冻结公共 gate，不把参考实现传给模型。
5. report.md 写明条件、版本、结论、失败原因和证据路径；summary.json 记录同一事实。分别记录材料自检、候选外置验收、框架 `delivery.complete`，只有本项目定义的全部条件满足才标记 passed。

manifest 至少包含框架/项目提交、输入 SHA-256、模型与推理配置、预算、环境、实际命令，以及配置/合同/账本/日志的索引。启动前补齐；结束后记录 task/run ID、selected commit、外置验收命令及输出摘要。保留未知值为 null，并写明原因；不将 token 换算成没有价格依据的费用。

reports 只提交可分享摘要及必要的小型证据，完整运行原件留在 runs；框架已保存的日志只索引，不复制一份。提交前检查暂存区，不提交依赖、密钥、嵌套 Git 工程或整个账本。

## 旧目录处理

旧 benchmark 用例、执行工具和 FP32 包已在此前退役。本次将剩余三份历史准备记录移至 [docs/reports/benchmark-preparation-20261024](../docs/reports/benchmark-preparation-20261024/preparation-20261024.md)，不保留 legacy 工具副本。旧的未跟踪 cache/projects/experiments 仍忽略，未经核实不删除原始数据。DMA 的既有对照记录迁入项目 reports，原结论和原始路径不改写。
