# 01: 数值目标与完成判定贯通

**What to build:** 用户只维护一处数值交付门槛，准备、运行进展、终验和观察结果一致区分“改善”“目标达到”和“任务完成”；有效中间冠军不被最终目标阻断。依据 [S4 规格](../spec.md)。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 新明确契约中 target 填入即为硬性数值交付门槛；未达标阻止完成并说明实际值和缺口，不再仅警告放行。
- [x] 同一门槛只写 target，不要求复制到 requirements；objective、constraints、target 和其他需求各司其职，Profile 不另提供验收标准。
- [x] 准备允许基线尚未达目标；100 ms 到 94 ms 的可信改善在正确性、约束、可比性与噪声规则满足时更新冠军，即使最终要求为≤90 ms。
- [x] 更快但结果错误的版本不成为冠军；无收益或失败候选及必要证据仍保留。
- [x] target 达到也不能跳过其他必需验收；无 target 的开发/探索任务不被强加数值目标，明确可选需求保持可选。
- [x] CLI、报告及只读观察不将 target_met、冠军或 closed 单独表示为完整交付通过，提供对应依据和缺口。
- [x] 历史冻结契约与报告不批量改写或重验；旧 target 仅为期望时，通过已有 revision 规则明确新契约，不静默改变历史语义。
- [x] 沿现有运行/交付入口用受控测量覆盖上述行为，并运行相关回归；修改范围内清理旧警告放行等失效路径，不新增策略插件或重复状态账。



## Comments

2026-10-31 — 实施与验收：

- `d594152`：新 Run 冻结硬 target 语义，终验未达标产生 block，报告单列 target_met 与 target_policy；冠军比较继续复用原有正确性、约束、可比性及噪声规则。100→94（target≤90）可晋升，但终验失败；80但算错及98无收益均保留原件且不晋升。
- 单一 target 无需 requirements 副本；达到 target 仍阻断缺少必需证据的交付。无 target 正常验收；required=false 在终验及只读观察中均保持可选（修复观察入口把可选缺覆盖判为不一致的分支）。ONBOARDING 示例去掉数值门槛重复定义。
- 历史 Run 缺少新 policy 标记时沿用 advisory，包括同 revision 的后续 Run；不批量改写契约、冻结文件或报告。旧 target 同数值升级可经新 revision 与用户 confirmation 的 `changes.target_policy={old:advisory,new:required}` 明确授权；测试核对旧报告字节保持、无新增执行 Run。
- 红→绿：新增数值目标高层案例先重现 complete=true 错误；可选项案例先重现 Observer unknown；同历史 revision 新 Run 案例先重现静默升级。修复后5项新验收通过（10.73s）；相关回归 `test_engine.py test_research_loop.py test_brief.py -k 'not results_http_entry'` **191 passed**（331.16s）；`git diff --check` 通过。另补的历史同 revision 续开检查已在最终5项验收中通过。
- 测试使用受控脚本 Worker 与本地 toy 评价器，真实账本、成果和只读 ObserverAdapter；未调用真实模型、未运行正式研究考试。未运行 HTTP TestClient 及 DSH 实机验证，不计入通过。

2026-11-01 — 验证记录补充：上述191项回归进程启动后，补充历史同 revision 续开断言时误将3行插到既有冻结权限测试；因此191项结果未覆盖该后加编辑。误插已在06实现 `62b2f29` 删除，冻结权限测试与新增legacy案例均纳入06最终相关组合回归，详见[06事项](06-standards-history.md)的验证记录。
