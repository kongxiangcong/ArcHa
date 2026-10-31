# DeepStack 来源登记

本目录为来源索引，不是考试工作区。现行 [四题](../README.md)中开发、探索、独立端到端使用 DeepStack；调优使用 Ramulator 2.0。旧六探索题和 bank 调优方案已撤回。

固定上游 [tile-ai/DeepStack](https://github.com/tile-ai/DeepStack) commit `17e21bf54115e11b9e7c6edc0b2d1723d25d022b`，主线发行材料。完整外部工程保留 `/root/DeepStack`；本地工作树有改动，题内只用该 commit 的 git archive，不复制工作树。公开源码与打包二进制并存，并非整个项目闭源；按发行版保留许可证。

原始发行版分别封装到探索与端到端独立工程，CPython 3.11 x86_64 Linux CPU 环境已运行自检。详见 [准备报告](../../docs/reports/benchmark-preparation-20261031/README.md)。官方示例成功证明环境可用，不证明完整建模解释或硬件准确性；正式研究待 S6。

机器来源见 [source.json](source.json)。本目录旧 [TASK.md](TASK.md)为历史需求入口，当前考试以四题各自 TASK.md 为准。
