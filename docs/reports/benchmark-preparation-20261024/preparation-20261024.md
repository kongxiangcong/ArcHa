# 评测项目准备验证 — 2026-10-24

四张任务均已准备为独立 Git 项目，含研究地图、task-brief、合同、冻结评价器和当前 ArcHa 工作树 runtime 快照。
模板执行开关关闭；`experiments/validation-*` 是仅用于 check/preflight 的验证副本，没有调用模型，没有 run 或 promote。

| 任务 | 本机实测基线 | 目标 | ArcHa preflight |
| --- | ---: | ---: | --- |
| vliw-pack | 1234 bundles | ≤1100 | 通过，correct=1 |
| kernel-opt | 147734 cycles | ≤74000 | 通过，correct=1 |
| ft06-search | 最差 makespan 61，均值 61 | 最差 ≤59 | 通过，correct=1 |
| riscv-restore | remaining_cases 3 | 0 | 通过，correct=1 |

完整机器可读记录见 [preparation-20261024.json](preparation-20261024.json)，依赖实况见 [environment-20261024.txt](environment-20261024.txt)。
JSON 包含框架提交及源码摘要、上游提交、评价器摘要、基线指标、gate 与命令墙钟。
这些时间来自准备验证，部分操作并行执行，不是配置间性能排名，也不是优化后成绩。

验证结果：

- 4 份 brief 通过当前 `load_brief` 结构检查；4 份隔离项目真实 `preflight` 通过。
- `python -m pytest benchmarks/tests -q`：11 passed。最终汇总逻辑调整后，成本汇总和目录防覆盖 2 项定向复验也通过。
- 正确但未达目标返回 0；空打包错误、错误 RISC-V 语义和候选自造的缺失依赖均被判失败。
- 评价前删除旧 metrics，错误候选不能沿用成功报告。
- xDSL 已验证部分恢复 3→2→1→0；用本地上游原始实现作为评价器正对照，未把答案放回基线。
- FT06 重复测量一致；注入额外 steps 字段被拒绝。另在缓存副本只把邻域设为 critical，得到最差 56、均值 55.3333，证明目标在固定预算内可达。这只是适配器正对照，不能算作 ArcHa 自主优化成果。
- 合成账本验证 reviewer 分账、总 tokens、未知 USD 留空；合成数据只存在缓存测试夹具，不进入实验结果表。
- 冻结匹配规则验证覆盖所有应冻结源码、排除可改路径；项目与实验同名目录不可覆盖。

准备期间遇到并已处理：pip 下载停滞（改用 uv 安装同一隔离环境）、JobShopLib 实际导入还需要 pandas、当前 xDSL 寄存器 API 与旧用法不同。
首次 xDSL preflight 使用逐文件规则，检查过慢而中断；随后改为等价目录规则，再在新的 validation 实验中通过。
初始项目草稿和被中断的准备记录保留在 `cache/initial-draft-projects`、`cache/initial-preflight`，不混入正式实验对比。

边界：未测试模型表现、真实多轮搜索、预算耗尽、暂停恢复或最终 reviewer；未跑 xDSL 全项目测试。
本次只新增 `benchmarks/`，没有替换用户已有的框架修改，也没有提交或推送 ArcHa 父仓库。
