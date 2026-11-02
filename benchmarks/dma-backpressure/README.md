# DMA 背压闭环冒烟

用途是检查 ArcHa 能从任务接入、实现、验证走到正式终验。任务为人工合成的描述符执行器，Python 3.10+ 与 Git 即可准备；没有数值优化目标，也不用于证明 ArcHa 比直接 Codex 更快或硬件模型更准确。

- [TASK.md](TASK.md)：保持既有需求、接口、手算时序和完成条件。
- [starter/](starter/)：串行初始实现、四项公开检查和示例输入；初始功能失败是预期现象。
- [examiner/acceptance.py](examiner/acceptance.py)：外置逐周期参考、82 个固定种子输入及有效/非法 CLI 检查。
- [examiner/test_materials.py](examiner/test_materials.py)：手算锚点、错误实现拒绝、时移不变量、CLI 正负对照；只供操作者执行。

## 材料自检与准备

以下命令从 ArcHa 仓库根运行，不调用模型：

```bash
python3 -m unittest discover -s benchmarks/dma-backpressure/examiner -p test_materials.py -v
python3 benchmarks/dma-backpressure/prepare.py benchmarks/dma-backpressure/runs/20261030-smoke-01
```

prepare 拒绝已有目录；仅复制 TASK.md 与 starter 的文件到 project，初始化独立 Git 提交，创建 workspaces、acceptance、logs 和 manifest，并生成 `bindings.json` 模板以指定 project 外的工作树；不预建 .opc，以兼容初始化流程。日期和序号按实际运行调整，也可传入仓库外的新目录。若准备中断，保留目录并选新运行编号，不覆盖证据。

## ArcHa 执行

进入本次 `project/`，按 [公共约定](../README.md) 配置读取隔离；给主会话 TASK.md，通过 `archa-map → archa-task → archa-loop` 接入并完成任务。沿用三个技能和项目 runtime 的现有流程，不直接修改冻结合同以跳过接入。

完成 archa-task/onboard 后、首次 archa-loop 前，确认 `.opc/local/` 已由接入流程建立，再安装准备生成的绑定（RUN 替换为本次运行目录）：

```bash
cp RUN/bindings.json RUN/project/.opc/local/bindings.json
```

检查该文件的 workspace_root 指向同次运行的 workspaces，然后再启动 loop。

执行前将实际模型、推理配置、预算、技能/runtime 版本、命令及合同路径写入 manifest；配置不得在事后为成功补改。冻结公开 public_checks.py 和 TASK.md，允许修改 dma_model.py、添加开发测试与 README。外置 examiner 不作为 gate 传给 worker。

若在操作者环境使用已有项目 runtime 执行/恢复，CLI 形式如下（PROJECT、TASK、REVISION 替换为实际身份，不另建默认任务）：

```bash
python3 PROJECT/.opc/archa.py run -p PROJECT --task TASK --revision REVISION --deliver
```

记录 task/run ID、停止原因、selected commit、delivery 报告和账本路径。`run` 退出或候选保存不等于完成；终验读取 `delivery.complete`。本次目录整理未启动该步骤。

## 操作者外置验收

先将明确的 selected commit 导出到本次 `acceptance/candidate/`（例如 `git -C PROJECT archive SELECTED_COMMIT`，解包到该目录），避免误验主分支或任意工作树。然后从仓库根执行，替换 RUN 为本次运行目录：

```bash
python3 benchmarks/dma-backpressure/examiner/acceptance.py generate RUN/acceptance/inputs.json
python3 benchmarks/dma-backpressure/examiner/acceptance.py evaluate --candidate RUN/acceptance/candidate/dma_model.py --data RUN/acceptance/inputs.json --output RUN/acceptance/result.json
```

在模型执行前冻结验收器与数据摘要。以上命令仅由操作者运行；只把结果和必要失败描述交给框架，不交付 oracle。框架中声明的公共检查、README 及需求覆盖仍须独立通过。

## 冒烟通过条件

1. 真实模型执行完成接入、设计实现和正式终验；保留框架证据且 `delivery.complete == true`。
2. 对同一 selected commit 的公开检查、任务交付（包括 README）和外置 82 个函数用例及两种 CLI 检查全部通过；材料自检通过。
3. manifest 能定位固定输入、版本、配置、命令、task/run、selected commit、账本、终验和外置验收原件；记录读取隔离方式及实际边界。

暂停、预算耗尽、基础设施失败或仅候选正确均记录未完成，不能作为“ArcHa 能跑通”的通过结果。不要求与直接 Codex 比较或优化吞吐。

## 报告

[2026-10-29 历史对照](reports/20261029-comparison/report.md)及 [summary.json](reports/20261029-comparison/summary.json)保留“候选外置通过，但框架预算中断”的原结论，因此不算完整闭环冒烟成功。本次未创建虚构的 `20261030-smoke` 成功记录。后续真实运行按 `reports/<date>-smoke/` 保存 report.md、summary.json，完整原件在 runs 中忽略。
