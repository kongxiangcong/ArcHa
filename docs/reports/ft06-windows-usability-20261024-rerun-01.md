# FT06 Windows 可用性重跑 01

日期：2026-10-24，Asia/Shanghai。结论：**完整验收通过（保留前次额度失败）**。真实 ArcHa worker 一轮把 makespan 从 152 降到 55，独立原评测 PASS；未把冠军合并到 main。

## 实验身份与隔离

- 本轮根目录：`D:/dsh-proj/ArcHa/.tmp/usability/ft06-20261024-rerun-01`。从原 ZIP 重新解压，新建独立 Git；未复用旧合同、账本、求解器或冠军。
- 原包基线：`62ed6283d03052cee692e392b1739996b72d1833`；接入后基线：`36bc9bb47e421342112c32969ab884f1a0dadb58`。
- Run：`run-f8850de73bff`，task `t-main`，revision `r0001`；只有一个 run、一次搜索尝试，没有重启/预算重置。
- 冠军：`3eb6b0d911b510869a4b90844aacc97ea6b1a050`，`refs/heads/opc/t-main`；state=closed，stop_reason=target_met。
- 源码 HEAD 基础：`cb189f9b1649b87318422e220ae2e970a2dec6c8`，实际使用未提交工作树快照；不能用 HEAD 代替快照身份。
- 执行 runtime SHA-256：`01b7af1c29b1e7c632a2b47a6e2fabbf313609e72196421521933bb14b3639ae`。manifest 逐文件校验通过，保存在 logs/runtime-manifest.json。
- 已安装技能正文与仓库一致，但运行包原先落后三个文件（prompts.py、worker.py、engine.py）；用项目安装器同步并备份后才部署。
- 本轮后补的 Windows 起草指南已同步到本机技能，最终安装快照为 `bf3c6ebfcc0613d5e8115865c5ffc76332dfee174a1729af37c8a8686cb08cd3`。实验的冻结 runtime 没有随之升级；该指南的未来实际效果尚未重跑验证。

## 三阶段与模拟决定

1. **archa-map**：部署项目 runtime，实测原基线，形成单任务 R01 地图和占位文件。M01 为获授权的模拟方向选择。
2. **archa-task**：独立子代理只读本新工程，产出源码边界证据；主观察者核对关键来源、展示建议大纲，并记录 M02 模拟整体认可。brief-check 通过后真实 onboard 起草合同；ok=true，越界/只读输入变动均为空。M03 模拟认可常规接入选择；DECISIONS.md 保存 brief 路径、SHA-256、task/revision、预算和交接。
3. **archa-loop**：M04 模拟启动；确认无既有 run，启用执行，只提交核对后的 .opc 文件；check 和 preflight 通过后实际 run。M05 为最终验收决定：以真实原评测、重复测量、范围审计和 reviewer 结论判断，不以 worker 自述代替。

以上均来自本轮用户明确授权的模拟，不声称真人逐项再次确认。范围决策额外向真人提问 0 次。用户后续“继续”触发一次审核重试，不是新实验授权或预算重置。

## 原始基线与实验历史

原 `python -m unittest discover -s tests -v`：5/5，通过，exit 0。原 `python evaluate.py`：exit 2、NEEDS_IMPROVEMENT、valid=true、分数 152/120/19/38。退出码 2 被正确保留为合法未达标测量，不改为最终通过。

| 阶段 | 观察结果 | 证据 |
| --- | --- | --- |
| expert | 完整 hypothesis/changes/expected/falsifier，计划仅改 solver.py | a000001/expert 原始请求、事件、计划 |
| designer 自述 | 单测 5/5；评价 PASS，55/55/11/22 | designer-last.txt；此行仅是 worker 自述 |
| 引擎冻结验收 | 两道 gate 通过，correct=1，makespan=55，接纳 improvement | ledger、a000001 评价原件 |
| 引擎停止 | 第一次接纳后 target_met，没有第二次尝试 | report-before-review.stdout.txt |
| 首次 promote | 基线 152/152/152，冠军 55/55/55；reviewer 额度失败，promotable=false | promotion.stdout.txt |
| 用户继续后的 promote 重试 | reviewer=accept，promotable=true；仍未 apply | promotion-retry-02.stdout.txt 及对应完整 report.json |
| 导出后独立复测 | 原评价 PASS/exit 0，55/55/11/22；原单测 5/5 | independent-evaluate.*、independent-unit.* |

原 7 个受保护文件（评价器、grader、tests、任务定义和 README）与 ZIP SHA-256 一致；冠军相对接入基线仅 workspace/solver.py 变化。原始报告是生成物，声明为 scratch 并保留真实写入，未以 monkeypatch 或抑制报告绕过。worker 命令审计未发现旧实验路径；观察者没有给优化 worker 上轮答案，也没有代写 solver。

独立 reviewer 的最终摘要：Promote for the stated FT06 goal: makespan improves from 152 to 55. No blocking spec violations or unsupported claims found.。审核原件中的 requirement_findings 逐项给出 R1–R4 结论。promote 的 requirements 列表仍显示 R4=needs_review，这是传入 reviewer 前的覆盖状态，最终判断须结合 reviewer.verdict/requirement_findings。成功重试的 reviewer 直接用原 checker 复现四例，并跑原单测及额外边界检查；因只读工作树未运行会写报告的 evaluate.py 入口。该入口已由引擎和观察者独立原样执行，不能把两类证据混称为 reviewer 全部执行。

观察者源码核查：仅导入标准库 math/random；依据传入 jobs 构造操作交错序列、机器空档与负载下界，固定局部随机种子进行多起点退火。未发现 FT06 数据、目标阈值或预存答案硬编码。额外 16 个小输入（含空输入、不同长度、非连续/负机器编号、重复机器访问）通过原 checker 和独立成对冲突检查，且输入与全局 RNG 不变、结果可复现。这些证据不证明任意规模性能，也不替代独立 reviewer。

## 成本与预算

| 阶段 | 耗时 | tokens |
| --- | ---: | ---: |
| onboard 起草 | 656.986 秒（命令墙钟） | 1,160,782 |
| expert | 142.897 秒 | 97,935 |
| designer | 127.593 秒 | 286,136 |
| 优化循环合计 | 284.965 秒（账本），291.980 秒（命令墙钟） | 384,071 |
| 两次 reviewer 调用合计 | 165.267 秒（账本） | 157,971（已报告数） |

优化额度为最多 6 次 / 1800 秒 / 600000 tokens；实际 1 次，结束时余 5 次 / 1515.0 秒 / 215929 tokens。没有跨 revision 承接，因为无需新 revision。起草和最终验收分账；promote 会把 reviewer 费用追加到同一账本，因此最终 report spent 与优化结束时不同，不能把它们混为迭代成本。每次 promote 的完整墙钟见对应 .meta.json，含重复评价与进程开销。

审核重试后的最终账本为 450.232 秒、542042 个已报告 tokens（包含 reviewer）；仍未达到合同数值上限。两次 promote 命令墙钟分别为 104.238 秒和 157.188 秒。重复评价时间并未全部进入该账本 spent，因此以命令日志补足验收墙钟，不能将账本当成端到端计时器。

tokens 为 CLI 输入（包含缓存）加输出计数，不是价格；USD 未知。第一次 reviewer 在完成 usage 事件前额度失败，账本记录 0 tokens，**不能解释为实际免费或真实消耗为零**。主观察者与调研子代理的会话 token 未由 ArcHa 统计。引擎按调用结束后的 usage 检查额度，未证明能在一次调用中实时硬截 token。

初次实测于 00:39—01:06 完成主要执行，用户后续继续时才重试审核和打包；中间等待不计入引擎执行时间。不能用跨消息的自然时间差推断计算成本。

## 故障、恢复与通用修订

- 框架全量测试初次为 170 passed / 4 skipped / 2 failed；两项失败分别是外层沙箱拒绝 junction 和安装器私有临时目录访问。相同两测试在沙箱复现失败，在获授权宿主环境通过。最终覆盖为 **172 passed、4 skipped**，不是隐去初次红灯的单次全绿。
- onboard 自建适配器测试夹具遇到 Windows 私有 TemporaryDirectory ACL 问题，worker 自主改为继承工作区 ACL 的唯一目录，8 项协议测试通过；初次失败和成功事件均保留。原包测试未修改。
- 将这一目录规则加入通用 `opc/scaffold/ONBOARDING.md` 第 6 节；`docs/cross-platform.md` 追加外层沙箱诊断说明。只改指南，不更换正在执行的冻结 runtime；没有 FT06 专用引擎分支。
- 首次独立 reviewer 遭遇账户 usage limit，ArcHa fail-closed 阻止晋升。用户“继续”后显式重试，前次失败记录保留。本轮不更换账号/模型、不购买额度，也不以观察者意见伪造 reviewer verdict。
- 观察者两次轻微工具问题另记：初次版本探针用 Windows 默认文本编码，后按字节/UTF-8 读取；续跑时 transient store 丢失导致一次未启动引擎的路径错误，改为核实的绝对路径。均未改预算或 solver。
- 主仓库用户原有改动未回滚、未整体提交或推送。独立实验工程用于冻结的提交保留；主仓库 git diff --check 通过。

## 与上轮对照

对照来源：仓库 docs/reports/ft06-windows-usability-20261024.md；不把缺少记录的项推断为未执行。

| 项目 | 上轮报告 | 本轮证据 |
| --- | --- | --- |
| 最终 FT06 分数 | 56 | 55，原评价独立 PASS |
| 三技能链路 | 完成，但需多项框架修复与新 revision/run | 完成，单 r0001/run，无搜索阶段修复或重启 |
| 搜索恢复介入 | 有 CLI/runtime/schema 修复、暂停与预算承接 | 0 次；第 1 次真实候选直接接纳 |
| 临时输出处理 | designer 曾抑制报告写入；之后仅回归验证提示修复 | 本轮真实 designer 原样跑原评价并写 scratch 报告 |
| 研究计划/反馈 | 新反馈改动后未在该达标运行中重写 | 本轮计划含完整预测/可证伪条件；多轮反馈仍未走到 |
| 最终验收证据 | 原评价和单测复测；未记录 promote 三次重复与独立 verdict | 实际 promote、三次复测、需求覆盖和 reviewer 记录（含失败/重试） |
| 起草 tokens | 423,534 | 1,160,782，约 2.74 倍 |
| 达标 run tokens | 246,173 | 384,071，约 1.56 倍 |
| 达标 run 账本耗时 | 190.919 秒；另有前序 47.695 秒协议失败 | 284.965 秒；没有前序搜索协议失败 |
| 框架回归 | 145 passed / 4 skipped | 172 passed / 4 skipped（需分清权限复测） |

人工介入口径：本轮有 5 个获授权模拟决定；优化阶段观察者修复/重启 0 次；验证环境诊断 1 组（两项测试），onboard 自主恢复 1 次，首次审核外部额度阻塞 1 次并经“继续”重试。上轮报告列出 8 类问题，但没有统一人工操作计数，不能伪造精确次数差。

结论：启动与搜索链路更顺畅，报告写入修复获得真实 worker 证据，最终验收证据更完整；**不能声称更省时或省 tokens**。分数提升到 55 是一次新搜索的观察，不能单独归因于反馈机制。多轮修正假设、预算耗尽/中断恢复、较大实例、其他操作系统仍未验证；新 Windows 指南减少未来失败的效果也待下一次接入观察。

## 交付与续接

交付目录：`D:/dsh-proj/ArcHa/.tmp/usability/ft06-20261024-rerun-01/deliverable`。

- champion/：实际冠军源码与冻结 runtime；在该目录运行 `python -m unittest discover -s tests -v` 和 `python evaluate.py`。
- champion-source.zip：可运行源码及真实 evaluation_result.json。
- experiment.git.bundle：原始、接入与冠军提交和分支历史。
- ledger.sqlite3、evidence.zip：账本备份、命令日志、worker 原件和验收证据。
- evaluation_result.json、USABILITY.md：直接可读结果和本报告。

需求验收状态以对应 promotion/report.json 为准。若审核仍不可用，应在额度恢复后只重试 promote，不启动新 run 或重新搜索，不将观察者核查替代所要求的独立 verdict。
