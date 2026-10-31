# 操作者环境说明

## 已准备材料

四个 `runs/prepared/project` 是独立 Git 工程，`TASK.md` 为 Map 输入。每题入口见题内 `ENVIRONMENT.md`。只交付该工程；父目录 manifest、examiner、兄弟题及研究笔记保留在操作者侧。探索题提供完整发行版以免截断依赖，但任务范围仍限定于 3D 存储模块。

DeepStack 固定 `17e21bf54115e11b9e7c6edc0b2d1723d25d022b`；Ramulator 固定 `be93be78055d922aa1d4d33e15bcc8f2b0c61a9d`。原工程原地保留，导出不含未提交改动。探索/E2E 论文为 arXiv `2604.04750` 本地 PDF，文件哈希锁定到各题 manifest；论文发布时间/版本不当作源码版本。原始许可均随发行版保留。

共用只读 `.runtime/python`（CPython 3.11.18、依赖锁定见 `.runtime/requirements-resolved.txt`）及 `.runtime/cmake`；Ramulator 使用本机 GCC 13.3、C++20、Release `-O3 -DNDEBUG`。依赖固定导出到 source/ext，构建不联网。机器和工具链信息随准备报告记录。

## 本地命令

在仓库根目录运行：

```sh
python3 benchmarks/tools/prepare.py
python3 benchmarks/tools/isolate.py benchmarks/deepstack-development/runs/prepared/project -- python test_public.py
python3 benchmarks/tools/isolate.py benchmarks/ramulator2-optimization/runs/prepared/project -- ./build.sh
python3 benchmarks/tools/isolate.py benchmarks/deepstack-exploration/runs/prepared/project -- python -m pytest -q source/tests/test_custom_arch_profile.py
python3 benchmarks/tools/isolate.py benchmarks/deepstack-end-to-end/runs/prepared/project -- python source/examples/custom_accelerator.py
```

开发题初始实现故意抛 NotImplementedError，测试失败是预期起点。准备脚本遇到已有工作区会保留，不覆盖后续考试成果。当前复建脚本使用本机原始 repo 与既有 runtime 缓存（路径在脚本中）；它不是跨机器自动安装器。迁移时携带固定源码、依赖、PDF 和运行时，核对 manifest，不从浮动分支重取。

## 工具边界

Linux x86_64 Landlock ABI >=3 限制文件读取/写入，seccomp 禁止新 socket；允许题内读写、系统编译工具/库和共享只读 runtime。清空继承环境，HOME/TMPDIR 指向题内。探针验证含子进程继承、兄弟题与外部原工程不可读。

此启动器用于**本地执行工具**，不是已完成的 Worker CLI 集成。正式 S2 必须让文件读取、shell 及其他工具统一遵守同一边界，并把模型通信留在可信外层；不能先给宿主读文件工具再仅隔离 shell。ArcHa runtime/skills 需要以不含其他题和答案的最小材料提供。不同 Attempt 的固定输入/工作树与资源协调仍由 Engine 管理。

## 外置验收

开发题：

```sh
python3 benchmarks/deepstack-development/examiner/judge.py /absolute/candidate/project
```

判题器自检可重放：`python3 benchmarks/deepstack-development/examiner/selfcheck.py --output <新目录>`。参考实现仅在 examiner，公开 JSONL runner 冻结。判题器自检包含正例和错误实现反例；通过实例不等于数学上证明所有输入。

Ramulator：

```sh
python3 benchmarks/ramulator2-optimization/examiner/judge.py /absolute/candidate/project --output /absolute/new-report-directory --smoke
# 正式验收去掉 --smoke；output 必须是新目录
```

操作者先准备 `examiner/private/baseline-timed` 与 `baseline-observed`（构建脚本见 `examiner/prepare_baselines.py`）。前者冻结无探针原版二进制/库，后者为同版加观察探针的独立构建。候选按冻结源码范围检查并重新构建，事件构建在报告目录复制源码后加同一探针。基线自检时可复用已编译且来源相同的观察版；修改候选需重新构建。

12 个正确性实例涵盖四种模式、纯读/纯写/混合；逐事件哈希和完整序列化统计必须相同，并核查背压拒绝、刷新、选择和完成覆盖。观察版与原版统计同时核对。探针是操作者适配器，内部重构改变插入点时需核对再适配，不能静默跳过。LoadStoreTrace 沿用输入全部接收即终止，不 drain。

正式计时三族各 100,000 请求、五对交替顺序，固定一个可用 CPU 核；无其他计时工作并发。计时包含隔离启动器、进程启动、读 trace、初始化、仿真和统计；排除构建/生成输入，双方路径一致。记录每对墙钟、RSS、各族中位速度比与离散范围。几何均值 >1.05、单族 >=0.95、至少四对综合胜出且全部正确才通过。该 5% 为任务实用收益门槛，不声称等于普适统计置信界限；机器波动过大时完整重测，不按有利重复挑选。smoke 仅查环境/等价，不判提速完成。

两道探索题按公开 DELIVERY.md 进行外置证据核查，方法见 examiner/RUBRIC.md。操作者重放关键证据、核对来源，保留核心缺口；不制造唯一模型答案或自动字数评分。

本机同版本正式规模校准见 [准备报告](../docs/reports/benchmark-preparation-20261031/README.md)：综合中位速度比0.9989，单对波动可接近10%。因此不能以单次测量或5%阈值本身声称统计置信；有干扰/边界收益时完整复测。校准入口为 `examiner/calibrate.py`，在原版且无并发压力时运行。
