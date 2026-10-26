# 实验区

每次 `bench.py new` 创建一个唯一目录，目录已存在就拒绝，不能覆盖或复用冠军。

```text
<experiment-id>/
  manifest.json         配置、模板提交、框架逐文件摘要、依赖与环境
  project/              独立 Git 仓库、合同、运行时、工作区与账本
  logs/                 每次命令 argv、退出码、墙钟时间、stdout/stderr
  summary.json          原始 ledger 导出及汇总
comparison.csv          collect 生成的横向比较表
```

自动生成内容默认不提交。汇报时选取审阅后的摘要放到 `benchmarks/reports/`。
Anthropic 任务的候选方案不发布、不再分发；源码缓存和实验工程不进入 ArcHa Git。

`new` 只创建实验并启用该副本的执行合同，绝不调用模型。`exec ... run` 才启动迭代；
`exec ... promote` 才运行额外三次测量与独立 Codex reviewer，不自动 apply。
一份实验只对应一个 ArcHa run；恢复暂停可以继续同一 run，重新开始搜索请新建目录。

可版本化的执行与汇总脚本放在 [../scripts/](../scripts/)，本目录保留实验原件与清单，不放通用工具源码。
