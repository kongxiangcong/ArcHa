# 01: 贯通讨论、执行准备与首次探索轮次

**What to build:** 用户安装后只通过 `/archa-discuss` 与 `/archa-run` 开展研究：先多轮澄清目标及执行准备，必要条件满足且获得执行授权后启动，首轮结果实际回到 Expert 并影响下一步决策。明确任务同样经过准备讨论。

**Blocked by:** None (can start immediately).

**Status:** resolved

依据：[父规格](../spec.md)。已有未提交修改仅作为候选实现核对，不能代替本事项验收。

- [x] 两个新技能可以安装、部署并通过工程本地入口使用；旧四技能及冗余薄封装退役。安装时旧入口移入现有备份位置，不保留可发现的兼容别名，无关技能不受影响。
- [x] 开放探索支持多轮讨论和工程材料查证；未定锚讨论留在会话，目标足以指导下一步后才立项。只讨论时不启动正式探索，不强制预拆方向或另写交接材料。
- [x] 明确任务也讨论环境搭建方式、必要准备、环境就绪判据及验证依据，以及执行观测如何记录、判读并回到 Expert；复用已有答案，不因目标或执行授权已经明确而跳过准备。
- [x] 确认目标、范围、环境入口、完成判据和优化授权范围；必要准备满足且有执行授权后交接。沿用用户授权轮数，不重复索取相同授权，不增加准备状态或通用预检流水线。
- [x] Worker 配置检查保持只读，配置检查通过不等于任务环境就绪。初始化保留既有专题材料和配置，安装技能不隐式升级工程的固定运行时。
- [x] 在小型独立工程中，从真实技能交互分别验证开放探索与明确任务场景：缺少准备或执行授权时不启动，满足条件后实际执行，至少一次结果被 Expert 吸收并用于下一步决策或完成判断。
- [x] 复用安装、部署与本地 CLI 集成测试验证机械行为；真实技能对话、真实 Worker 执行与脚本模拟证据明确区分。仅格式校验、提示词检查或 CLI 成功不算完成主验收。
- [x] 相关调用入口和必要引用随本事项同步可用；完整 README 流程对齐由 04 在最终实现上完成。复用现有测试和证据，不新增测试框架或重复报告。


## Answer

已贯通两个已安装技能的讨论、准备与执行交接；开放探索与明确任务均经真实多轮对话和真实 Codex Worker 验收，必要准备与授权缺失时保持讨论。修复真实验收发现的 Codex 最终消息覆盖协议文件问题，保留固定运行时显式升级及配置不覆盖边界。专项回归 47 passed、3 Windows skipped。证据与失败过程集中记录如下；完整 README 流程仍由 04 对齐。

## Comments

2026-11-15：从 `integration/discuss-run-workflow` 的 `ed323fa` 开始，核对已有候选安装器、部署脚本和两技能。安装器沿用备份退役四入口，项目快照维持显式升级；本事项补齐两个技能的环境搭建、就绪依据与反馈回路门槛，并同步 README 的入口摘要。未增加状态、接口或预检流水线。

TDD 的已安装技能行为 seam：安装到 `/tmp/archa-01-acceptance/skills`，使用实际独立 Agent 对话（通过工具发送验收用户消息），不是字符串断言或 scripted Worker。明确任务 red 输入为“研究这个小工程怎样验证整数求和正确性，只调查，不改工程代码。授权最多 1 轮探索，请开始”，目标目录为空。旧技能实际创建专题、通过 check 后回答“拟执行 … run”，未讨论准备；验收 harness 当时禁止真实启动，因此只证明过早交接意图，不声称已运行。更新技能后，以新空目录复测同一输入：Agent 在初始化前询问验证对象与整数语义，提出观测/预期值/判读反馈，明确保留已有一轮授权。准备问题由真实对话暴露后才修改技能；未为技能措辞添加耦合测试。

机械回归：`/tmp/archa-results-venv/bin/python -m pytest -q tools/tests/test_skill_installer.py tools/tests/test_research_skills.py tools/tests/test_topic_skills.py tools/tests/test_project_layout.py opc/tests/test_topic_cli.py opc/tests/test_platform.py` → **46 passed, 3 skipped**（30.17s；Windows 专属跳过）。这些包含脚本 Worker 的确定性回归，仅证明安装、部署、只读 check、材料保留、显式升级和 CLI 行为，不用来推断真实技能或模型行为。系统默认 Python 没有 pytest，复用已有测试 venv。

真实模型环境探查：沙箱内最小 `codex exec` 返回 `failed to initialize in-process app-server client: Read-only file system (os error 30)`；按已授权的受控验收在 `require_escalated` 下重试，Codex 0.169.0 / gpt-6-astra 实际返回 READY。没有改变全局技能、配置或认证；下述真实 Worker 使用项目本地配置与默认模型。

开放场景真实对话（同一独立 Agent 的连续回合，工程 `/tmp/archa-01-acceptance/open`）：用户先说“还不清楚该关注正确性还是性能，先帮我讨论方向”，Agent 询问用途、输入类型和规模，仅读技能、没有建文件；用户继续“整数、理解正确性、担心大整数抵消，没决定立项，没有授权执行”，Agent 区分 int 与 float 路径并继续澄清，仍未初始化或实验。第三回合提供工程，明确精确求和目标但仍不授权，Agent 实际读取 README 与源码，提出 Python/import/简单调用的就绪依据，逐例输入/整数 sum 参照/实际值或异常的观测，以及 Expert 吸收方式；明确“未运行 Python、创建文件、初始化专题或启动探索”。第四回合用户确认这些约定并授权准备与 1 轮探索，才交接执行。开放讨论和明确任务的准备缺口均以真实模型响应验收；消息由验收执行者发送，未伪装为外部用户生产会话。

真实 Worker 首次失败揭示额外缺陷：默认 Codex 的 `-o {output_file}` 将模型亲自写出的 probe/result/state 覆盖为最终聊天摘要，finalize 发布报 `STATE.md: missing # Exploration State header`。旧明确任务专题 `explicit-green/.archa/topics/integer-sum` 保留该原始失败：completed_rounds=1、next_action=expert_finalize、权威 STATE 未吸收结果，故不算主验收通过。最小修正删除默认 preset 的 `-o`，继续使用既有文件输出协议。新增本地 CLI seam 回归，以外部 Codex 命令替身重现最终消息覆盖语义：修正前 probe 从预期问题变成 `Done; see the file I wrote.`，修正后完整 probe/result/finalize STATE 均保留。替身只用于回归；随后再用真实 Worker 验证。安装后的固定运行时必须停止后显式 `--update`；既有自定义 command 不自动迁移，README 说明保留 workers.json 及移除自定义 `-o {output_file}` 的边界。

修复后的同组机械回归：**47 passed, 3 skipped**（32.52s）；Windows 专属用例留待 CI。既有缺配置默认 Codex 测试的命令夹具同步改为遵循文件输出 prompt，不再依赖已移除的 `-o` 传路径。`git diff --check` 通过。

明确任务修复后真实验收：同工程显式更新运行时并新建 `integer-sum-fixed`（沿用准备答案，额外授权一轮验证修复，原失败专题未改写）。运行退出 0，`COMPLETED / completed_rounds=1 / max_rounds=1 / activity=idle`。完整证据在 `/tmp/archa-01-acceptance/explicit-green/.archa/topics/integer-sum-fixed/{GOAL.md,STATE.md,steps/step-01/probe.md,steps/step-01/result.md}` 及同轮角色日志：10 例实测，5 通过、4 错值、1 OverflowError；例如 `[9007199254740993]` 预期 9007199254740993，实得 9007199254740992。STATE 明确引用 result，吸收浮点转换机制、适用范围、剩余未知，并据反例判定调查完成；COMPLETED 不代表实现正确。源码未改，未生成额外报告。真实探针额外采集了源码 SHA-256，非本事项新增生产逻辑；保留原始记录，不据此扩展实现校验。

开放场景旧运行在收尾时正常 stop，保留旧 `exact-integer-sum` 专题的 1 轮及失败日志；显式更新固定运行时后，以同一目标与准备约定新建 `exact-integer-sum-fixed`，另授权一轮修复验收。真实 Executor 完成 14 案例／28 次调用，7 案例精确、4 错值、3 异常；完整 result 已发布，包含原始观测的路径和复现命令。原始材料保留在 `/tmp/archa-01-acceptance/open/.archa/topics/exact-integer-sum-fixed/`。

开放场景最终通过：`COMPLETED / completed_rounds=1 / max_rounds=1 / error=null / activity=idle / publishing=false`。STATE 实际吸收 result，区分输入舍入、求和舍入、范围异常，保留抵消成功案例与跨 Python 版本限制。两场景均未改源码、未生成报告；两组 Worker 均为真实 Codex preset，每角色 180 秒上限，无模型覆盖。未启用全局技能或新增测试框架。已清理仅用于 red 的空工程、临时安装备份及准备字节码；保留两个可复用工程、原始失败/成功轮次与运行时升级备份。两个成功专题均已 COMPLETED，后续不能重开；旧失败专题结果正文曾被覆盖，不应当作完整可用证据继续研究，可在相同工程中按后续授权新建专题。除 Windows 专属回归待 CI 外，本事项无剩余阻塞。
