# ArcHa FT06 Windows 可用性重跑 02

日期：2026-10-24（Asia/Shanghai）。结论：**三阶段闭环完整跑通，真实 ArcHa worker 一轮把 makespan 从 152 降到 55，独立原评价复测 PASS，独立 reviewer 首次调用即 accept；未合并到 main。** 本轮没有 worker 失败、没有基础设施故障、没有重启搜索；观察者修复了 1 个框架身份元数据缺陷。仍有两项未在真实运行中验证（多轮反馈、预算耗尽/中断恢复），并暴露了一个成本计量问题：把最终 reviewer 计入后账本 609,218 tokens，超过用户给定的 600,000，`budget_left` 变为负数。

## 测试目的和边界

按用户要求模拟用户，顺序执行 archa-map → archa-task → archa-loop，验证当前版本（HEAD `a1c50ca`）的接入与自动迭代是否真的可用，并比较与上轮报告的差异。

输入是用户提供的 `ft06-autoloop-smoke.zip`，只允许候选修改 `workspace/solver.py`；目标仍是 makespan ≤59，原评价器、grader、tests、task.json、TASK.md 不得修改。观察者不代写 solver、不把上轮答案给优化 worker、不修改目标或评价器。本轮未调用外部求解器。

以下操作是**用户授权的模拟决定**，不是真人逐项确认：M01 方向选择、M02 整体大纲确认、M03 常规接入决策、M04 启动迭代、M05 最终验收。范围决策向真人提问 0 次。

## 实验身份与隔离

- 本轮根目录：`D:/dsh-proj/ArcHa.tmp/usability/ft06-20261024-rerun-02`。指定目录 `rerun-01` 已存在且非空（10468 个文件），按规则递增新建本目录，未覆盖旧实验。
- 原始 ZIP：SHA-256 `1b2da9beeb51b65a2cae91fdf917d523762d8a9dfa8f7f720aaa21b18a389a81`。从该 ZIP 重新解压并 `git init`，未复用旧合同、账本、工作树、求解器或冠军。
- 工程提交：`a8bd921`（ZIP 原样）→ `dc88dc8`（测试用 `.gitignore`）→ `6581e3b`（接入合同，正式基线）→ `2cc2fe3`（冠军，`refs/heads/opc/t-main`）。`main` 仍停在 `6581e3b`。
- Run：`run-8635affb7924`，task `t-main`，revision `r0001`；只有一个 run、一次搜索尝试，没有重启或预算重置。state=`closed`，stop_reason=`target_met`。
- 执行 runtime：源提交 `a1c50ca4297ab1105ea5fab3e71f604a6cf5bb83`，快照 SHA-256 `bf3c6ebfcc0613d5e8115865c5ffc76332dfee174a1729af37c8a8686cb08cd3`，30 个文件，逐文件校验通过，`differs_from_head=[]`。证据见 `logs/runtime-manifest.json`、`logs/skill-install.json`。
- 框架源码在准备期间移动过：开始为 `1fb72c2`，用户于 12:18:06 提交 `a1c50ca`（安装器短路径修复）。本实验固定部署 `a1c50ca` 的 runtime；之后用户的改动未进入本轮 runtime。观察者的未提交修复（`skills/archa-map/scripts/initialize.py` 及回归测试）不属于 runtime 文件，未影响冻结执行。
- 已安装技能与仓库对比：`archa-map`、`archa-task`、`archa-loop` 的正文逐文件一致；随后用 `tools/install_research_skills.py` 重装以纳入修复，旧安装保留在 `~/.codex/skill-backups/`（本轮两次重装各 3 份，共 6 份），运行时快照随安装重建并逐文件校验。
- 隔离工作树：`<根>/worktrees/research-project/t-main/`，运行结束后已清理为空；账本与原件在 `.opc/local/`，未进入 Git。

## 三阶段记录

1. **archa-map**：部署项目 runtime（`.opc/runtime` + `.opc/archa.py`），实测原基线，形成单任务地图与占位文件。M01 选择 R01 激活、R02 作为鲁棒性方向 parked。
2. **archa-task**：派只读 sub-agent 调查源码边界，产出 `evidence/20261024-source-boundaries-ie1.md`（冻结边界、退出码、四实例、合法输出约束、报告覆盖副作用）。主观察者核对关键事实与来源，展示建议大纲并记录 M02 模拟确认，生成 `task-brief.md`；`brief-check` ok=true。随后真实 onboard worker 起草合同：`ok=true`，592.747 秒，904,757 tokens，`changed_outside_opc=[]`，`changed_protected_opc=[]`。观察者核对目标、范围、预算、评价器与简报摘要后记录 M03 与交接（`DECISIONS.md`）。
3. **archa-loop**：确认无既有 run，启用执行，只提交核对过的 `.opc` 接入文件（48 个文件，提交 `6581e3b`）；`check` 通过后 `preflight` 通过（基线 makespan=152、correct=1、unit_tests_passed=5，原评价 exit 2 被正确保留为合法测量），随后真实启动 `run`。

## 原始基线与实验历史

在干净解压工程上实测：`python -m unittest discover -s tests -v` → 5/5 通过、exit 0；`python evaluate.py` → exit 2、`valid=true`、`status=NEEDS_IMPROVEMENT`、`score=152`，四例 152 / 120 / 19 / 38。exit 2 是**合法但未达标**，未改写为最终通过。

| 阶段 | 观察结果 | 证据 |
| --- | --- | --- |
| expert | 计划含 title/hypothesis/changes/expected/falsifier 与 `exhausted=false`，仅改 solver.py | `attempts/a000001/expert/expert-last.txt`、`plan.json` |
| designer 自述 | 仅改 solver.py；单测通过；原评价 PASS，55/55/11/22 | `designer-last.txt`（仅 worker 自述） |
| 引擎冻结验收 | unit gate 4.539s、evaluate gate 9.853s 均 passed；makespan=55、correct=1、unit=5、原评价 exit 0 | `eval/evaluation.json`、ledger |
| 引擎停止 | 第 1 次接纳 improvement 后 `target_met`，未进入第 2 次尝试 | `run-01.stdout.txt`、`views/STATE.md` |
| promote 复核 | 基线 152/152/152，冠军 55/55/55；reviewer=accept，promotable=true，未 apply | `promotion-1792817058/report.json` |
| 导出后独立复测 | 原单测 5/5 exit 0；原评价 PASS exit 0，55/55/11/22，8.4957s | `independent-unit.*`、`independent-evaluate.*` |

## 当前版本验收流程的实际验证

- **合同与门**：onboard 生成薄适配层 `.opc/eval/evaluate.py`，原样调用根 `evaluate.py` 与 `unittest discover`，把合法退出 0/2 映射为测量、3 及其他候选错误映射为失败、工具/冻结输入/超时映射为 75。`check` 在起草阶段准确报出“执行开关关闭 + `.opc` 未提交”两项，提交后通过；`preflight` 在基线上真跑两门。原评价器未修改。
- **scratch 路径（58f0918 的提示修复）**：设计者提示实际包含 `scratch` 列表；真实 designer 直接运行原评价器并写出 `evaluation_result.json`，未使用 monkeypatch 或抑制写入。沙箱分类为 `editable=["workspace/solver.py"]`、`scratch=["evaluation_result.json"]`、`violations=[]`，候选补丁只含 solver.py。对照组上轮报告中的“设计者曾 monkeypatch 抑制报告写入”问题在本轮**有真实反证**。
- **计划完整性（1fb72c2）**：`validate_plan` 现在要求 title/hypothesis/changes/expected/falsifier 与 files；真实 expert 返回了全部字段，schema 也要求 `exhausted`。但旧实现同样会接受这份完整计划，因此本轮真实运行**不能单独证明**新校验带来的差异；差异由 `opc/tests/test_engine.py` 的参数化回归覆盖（缺失/空白/非字符串、空路径）。
- **实测证据传给下一轮（1fb72c2）**：第 1 次尝试的 expert 上下文 `history=[]`，一次达标即停止，第二轮从未发生。因此“把原假设、预期、可证伪条件与实测 gates 传给下一轮”只有单测证据（`test_next_expert_receives_original_plan_and_measured_evidence`、`test_failed_gate_history_preserves_failure_without_inventing_metrics`），**没有真实多轮运行证据**。
- **Windows 短路径安装器修复（用户 a1c50ca）**：`tools/tests/test_skill_installer.py` 在本机通过；本机 TEMP 不含 8.3 别名，真实安装未触发该路径，属于“测试覆盖、运行未触发”。

## 最终结果

- Run：`run-8635affb7924`；state=closed；stop_reason=target_met。
- 冠军：`2cc2fe3491be851c9dd04153e56791e36772c8c6`，`refs/heads/opc/t-main`；未 promote 到 main。
- 引擎测量：makespan 152 → 55（+63.82%），correct=1，unit_tests_passed=5，原评价 exit 0 / PASS；只用 1 次尝试。
- 独立复测：原单测 5/5；原评价 `PASS`、exit 0、55 / 55 / 11 / 22、8.4957 秒（单次观察）。
- 受保护文件：`evaluate.py`、`grader/check.py`、`grader/instances.py`、`tests/test_grader.py`、`task.json`、`TASK.md`、`README.md`、`evaluation_result.json` 共 8 个文件，在 ZIP 基线提交与冠军提交之间逐字节相同。
- 候选范围：`git diff --name-status 6581e3b 2cc2fe3` 仅 `M workspace/solver.py`（+91/−4）。补丁未含 `.opc/`、评价器、测试、报告或缓存。实际应用过的 `candidate.patch` 同样只含这一个文件。
- 同一评分器：基线、候选与 promote 的 3 次重复测量共 8 次 `evaluation.json`，`evaluator_digest` 均为 `f2b3e8709c21…`、`toolchain_digest` 均为 `85c59b155691…`，说明比较没有跨评分器或跨工具链。
- 最终算法：由输入计算各作业总时长与机器负载下界；以作业编号序列编码操作交错，用最早空隙插入解码；局部 `random.Random(0)` 做 24 × 4000 次固定种子模拟退火，严格更优才更新全局最优。只导入 `math`、`random`，未发现 FT06 数据、55/59 阈值、实例识别分支或预存答案。
- 补充独立检查：10 个小输入（空输入、单操作、重复机器访问、非连续机器编号、不同作业长度等）+ 40 个随机小实例，全部通过原 `grader.check`；FT06 两次调用结果一致；输入未被修改；全局随机状态未改变。证据 `independent-edge-cases.*`。
- 独立 reviewer 结论：`accept`，R1–R4 均给出满足判断，并提示证据不支持“任意实例最优或大规模性能保证”。`applied=false`，未动用户分支。

## 成本与预算

| 阶段 | 耗时 | tokens |
| --- | ---: | ---: |
| onboard 起草 | 592.747 秒（命令墙钟） | 904,757 |
| expert | 117.401 秒 | 92,775 |
| designer | 173.382 秒 | 381,117 |
| 引擎评价（基线 + 候选） | 15.830 秒 | 0 |
| 优化循环合计 | 306.613 秒（账本） | 473,892 |
| promote（3 次复核 + reviewer） | 118.991 秒（命令墙钟） | reviewer 135,326 |

优化额度为最多 6 次 / 1800 秒 / 600000 tokens；实际用 1 次 / 306.6 秒 / 473,892 tokens，关闭时余 5 次 / 1493.4 秒 / 126,108 tokens。起草与迭代分账；promote 把 reviewer 费用追加到同一账本。

**计量缺口（未解决）**：把最终 reviewer 计入后，账本合计 609,218 tokens、373.166 秒，`report` 的 `budget_left.tokens` 变为 **−9,218**。优化循环本身没有超预算，但用户给定的 600,000 worker token 上限若包含最终独立审核，本轮实际超出 9,218。引擎在 run 关闭后不再做预算检查，`promote` 也没有预算门。本轮不擅自改变预算语义（是“搜索预算”还是“含验收总预算”需要用户决定），如实记录为待决问题。

另外，按当前单次成本（约 47.4 万 tokens），600,000 预算在 `admit()` 的均值估算下**只够再来一次尝试**：第 2 次尝试会因 `s["tokens"] + est_tok > max_tokens` 在开始前被拒绝。因此“最多 6 次尝试”在当前 worker 成本下实际不可达，一次失败就可能直接进入预算耗尽。上轮也存在同一量级（384k/600k），不是本轮新引入。

tokens 为 CLI 报告的输入（含缓存）加输出计数，不是价格；USD 未知，不能解释为零成本。观察者会话与调研 sub-agent 的 token 未由 ArcHa 统计。自然时间中的等待不计入引擎执行时间。

## 故障、恢复与通用修订

- **无 worker/引擎故障**：0 次 worker 失败、0 次连续 INFRA、0 次暂停/重启、0 次预算重置。
- **修复 1（框架身份元数据）**：`skills/archa-map/scripts/initialize.py` 用“工作树原始字节 vs HEAD blob”判断 `differs_from_head`，在 `core.autocrlf=true` 下把 8 个干净文件误报为改动（`LICENSE`、`opc/adapters/codex.py`、`opc/adapters/dsh.py`、`opc/domains/command.py`、`opc/scaffold/{__init__,brief,evaluate_template}.py`、`opc/scaffold/ONBOARDING.md`）。改为用 `git diff --name-only HEAD` + `git cat-file` 判定，并新增回归测试 `test_snapshot_ignores_line_ending_only_differences`；修复后同一安装的 `differs_from_head=[]`。该修复未提交，留在主仓库工作区供审阅。
- **用户并发提交**：准备期间用户提交 `a1c50ca`（安装器 8.3 短路径修复 + 新测试）。本实验记录 HEAD 移动并固定部署该版本；用户的 `docs/` 改动与 `docs/reports/` 未被回滚。
- **观察者工具问题**：首次调用日志包装器时把 `.py` 当可执行文件直接启动，得到 `WinError 193`；改为显式 `python` 启动后正常，未改 ArcHa。控制台中文显示曾出现乱码，核查后确认落盘日志与账本均为正确 UTF-8，属显示层编码，不是产品缺陷。
- **未掩盖的失败证据**：本轮准备阶段的框架全量测试为 172 passed / 4 skipped、0 failed（基线）；观察者修复与用户提交之后，最终全量为 **174 passed / 4 skipped、0 failed**（532.27 秒），新增的两项分别是 CRLF 身份回归与安装器 8.3 短路径回归。两次结果分开记录（`logs/framework-tests.json`），不把“先红后绿”或“基线全绿”混成一次。旧的 172 项没有出现红灯；本轮真正的新失败只有最初被误报的 8 个文件身份，已用测试固定。

## 与上两轮对照

| 项目 | 上轮报告（20261024） | rerun-01 | 本轮 rerun-02 |
| --- | --- | --- | --- |
| 最终 FT06 makespan | 56 | 55 | 55 |
| 原评价独立复测 | PASS，exit 0 | PASS，exit 0，55/55/11/22 | PASS，exit 0，55/55/11/22 |
| 搜索尝试 | 1（r0002，另有暂停的 r0001） | 1 | 1 |
| 搜索期故障/重启 | CLI、runtime、schema 多项修复 + 暂停 + 新 revision | 0 | 0 |
| onboard tokens | 423,534 | 1,160,782 | 904,757 |
| onboard 墙钟 | 未记录 | 656.986 秒 | 592.747 秒 |
| 迭代 tokens | 246,173 | 384,071 | 473,892 |
| 迭代账本耗时 | 190.919 秒（另有 47.695 秒前序失败） | 284.965 秒 | 306.613 秒 |
| 最终审核 | 未记录 promote 与 verdict | 首次额度失败，用户“继续”后 accept | 首次调用即 accept |
| reviewer 计入后账本 | 246,173 | 542,042 | 609,218（超 600k 9,218） |
| 框架回归 | 145 passed / 4 skipped | 172 passed / 4 skipped | 174 passed / 4 skipped（含新增 2 项） |
| 观察者修复 | 8 类问题 | 1 组环境诊断 + 1 次重试 | 1 个框架缺陷；0 环境故障 |

人工介入口径：本轮 5 个获授权模拟决定，真人提问 0 次；优化阶段观察者修复/重启 0 次；最终 reviewer 无额度失败。上两轮没有统一的人工操作计数，不能伪造精确差值。

## 哪些改进有实际证据，哪些仍未验证

有实际证据：

1. **接入到达标一次跑通**：从 ZIP 到 champion 无故障、无重启，`preflight` 与 `run` 的退出码和账本一致。
2. **scratch 路径暴露生效**：真实 designer 原样运行冻结评价器并写出报告，报告被正确排除在候选补丁外，`violations=[]`。
3. **验收证据更完整**：3 次重复测量（152/152/152 vs 55/55/55）、受保护文件逐字节比对、范围审计、独立 reviewer 首次 accept。
4. **身份记录不再误报**：修复后 runtime 清单 `differs_from_head=[]`，与“工作树干净”的事实一致。

仍未被真实运行验证：

1. 多轮反馈：`history` 非空时的“原假设 + 预期 + 可证伪条件 + 实测 gates + champion_before”传递，仅有单测覆盖；本轮一轮达标使该路径没有发生。
2. 预算耗尽、停滞、暂停/恢复、INFRA 止损：本轮都未触发。
3. 引擎不保证严格 1800 秒 / 600000 tokens 的实时硬截止（OI-4）；本轮实际未触碰时间上限，但 token 计量如上所述有归属问题。
4. 更大规模、异常输入性能、其他操作系统与 Python 版本未验证；补充的 40 个随机小实例只证明合法性，不证明性能。
5. Windows 8.3 短路径安装器修复在本机未被真实 TEMP 触发。

未解决、需用户决定：

- **reviewer 费用归属**：是否把 `promote --review` 的 worker tokens 计入合同 `max_tokens`。若计入，本轮超 9,218；若不计入，`report`/`budget_left` 不应把 reviewer 混进 run 预算并显示负数。
- **R4 在 promote 的 requirements 列表仍显示 `needs_review`**，即使 reviewer 已给出 R4 满足判断；最终结论需读 `reviewer.verdict/requirement_findings`。这是展示层歧义，与上轮相同。
- 合同 `frozen=[]`：因为 editable 只有单文件，非 editable 改动仍会被判 violation，功能上没有缺口；但合同正文没有显式列出受保护路径，可读性弱于显式列表。

## 交付与续接

交付目录：`D:/dsh-proj/ArcHa.tmp/usability/ft06-20261024-rerun-02/deliverable`。

- `champion/`：导出的冠军树（含冻结 runtime 与合同）；在该目录运行 `python -m unittest discover -s tests -v` 和 `python evaluate.py` 可直接复现。
- `champion-source.zip`：可运行源码及真实 `evaluation_result.json`。
- `experiment.git.bundle`：ZIP 基线、接入提交、冠军提交及 `opc/t-main` 分支历史。
- `ledger.sqlite3`、`evidence.zip`：账本、命令日志、worker 原件、gate 回执与验收证据。
- `evaluation_result.json`、`USABILITY.md`：机器可读结果与本报告。
- `SHA256SUMS.json`：上述交付物摘要。

本轮结束于“达标 + 独立复核 + 报告”，未自动晋升；若用户要继续，应显式决定是否 `promote --apply`，以及任何新搜索都要在新授权和新目录中进行，不复用本轮预算或账本。

## 验证范围

本轮验证的是：该 ZIP 工程在本机 Windows / Python 3.14、Codex CLI `0.164.0-alpha.11.1` 环境下，从接入到一次自动迭代达标的完整闭环与可复核性。它不证明任意项目都能自动优化，不证明所有 CLI 版本/操作系统组合兼容，也不证明算法在大规模或其他实例上的性能。原包只有 4 个评测实例与 5 项测试，通用性仍需源码审阅与独立 reviewer 判断。
