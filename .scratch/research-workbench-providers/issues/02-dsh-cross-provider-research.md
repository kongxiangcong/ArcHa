# 02: 使用 DSH 与 Codex 交叉开展研究

**What to build:** 研究者可为 Expert 和 Executor 分别选择 DSH 或 Codex，并在后续探索轮次切换工具，继续使用已有研究材料。通过真实 CLI 验证本机模型配置、登录和内部工具环境，而不只证明参数能够拼装。

**Blocked by:** 01 — 通过新 Provider 配置完成 Codex／custom 研究闭环。

Status: ready-for-agent

**规格：** [Research Workbench 与多 Provider 执行](../spec.md)。本票交付 DSH 执行与真实跨 CLI 联调；原生 JSONL 保留为日志，工具事件归一和 L2 呈现由 05 交付。

- [x] DSH 使用无头模式、stdin 任务输入与原生 JSONL 输出，遵循同一暂存文件产物协议；不沿用将长 prompt 放入 argv 的启动方式。
- [x] model 为空时沿用本机 CLI 配置，指定模型时通过 DSH 原生接口覆盖；超时与环境覆盖有效，错误选项或配置失败提供可定位的上下文。
- [x] 已安装运行时包含 DSH Provider，默认配置仍为两个 Codex；未选择 DSH 的用户无需安装或配置它。
- [x] 通过真实子进程替身验证两种交叉组合、重拟／收尾的 Expert 配置继承，以及超过 128 KiB 的 stdin 输入；产物与原始日志可从既有状态和材料入口读取。
- [x] 同一专题在后续轮次切换 Provider 后继续利用权威材料，无需复制 CLI 会话、重置认知状态或重新计算已完成轮数。
- [x] DSH 非零退出、无产物或非法产物沿用已有失败与恢复行为，不把 CLI 失败当作专题阻塞，不让最终消息回填产物。
- [ ] 在小型临时工程中使用真实 Codex／DSH，分别跑通 Expert=Codex／Executor=DSH 及反向组合，并验证实际提交的探针、结果和状态。
- [ ] 真实联调覆盖指定模型、长 stdin、无交互执行和本机登录配置；通过 Agent 内部 shell 实际执行所需工具链命令，不能用入口环境检查代替。
- [ ] 联调沿用所选权限，不自动扩大权限；记录 CLI 版本、命令、退出与产物证据，并区分替身、源码核查和真实执行结果。若环境条件不满足，如实记录未通过项，不宣称本票已完成。
- [ ] 证据仅保留复现必需内容，清理无用途临时工程和数据；更新已有 Provider 使用说明，不新增平行配置文档或诊断账本。


## Comments

2026-11-18：实现原生 `dsh --profile headless [--patch <临时补丁>] --json -`，model 只覆盖 `agent-default-model.config.model`；默认不创建补丁，成功／失败／超时后清理。无 HOME、认证、权限重写。

- 源码核查：本机 DSH 0.2.2-rc.1 的 headless 输入契约及默认模型插件；原生 `--patch` 位于 `--json -` 前。后续真实启动纠正初次源码核查：普通 config 补丁替换整个对象，不能只写 model；改用原生配置钩子保留原 Provider 与 reasoningEffort。
- 替身进程：通过安装后的 `.archa/archa.py` 启动真实可执行子进程；两种交叉组合、132,000 字节以上 stdin、模型／环境覆盖、空模型、Expert 重拟／收尾继承、同专题切换 Provider 保留轮数和材料、非零／缺失／非法状态／超时失败恢复及补丁清理均覆盖。
- 真实联调初次被自动审批拒绝；用户随后明确授权“授权真实联调”，范围为原生登录、临时合成任务／状态、模型费用与内部 Python/shell，无仓库源码外发。授权后开始执行，结果见下。

验证：`/tmp/archa-results-venv/bin/python -m pytest opc/tests/test_topic_cli.py opc/tests/test_topic_rounds.py opc/tests/test_topic_recovery.py opc/tests/test_topic_process.py opc/tests/test_dsh_provider.py tools/tests/test_skill_installer.py -q` → 93 passed, 1 skipped；合入最新集成分支后 DSH 专项复跑 7 passed。

2026-11-18 原生配置回归：`ARCHA_TEST_DSH=/root/.local/bin/dsh /tmp/archa-results-venv/bin/python -m pytest opc/tests/test_dsh_provider.py -q` → 8 passed。原生 DSH 启动测试通过配置表达式确认 provider=`fixture-provider`、reasoningEffort=`fixture-effort`、model=`chosen-model`，随后空任务终止，不发模型请求。此测试曾揭示并修复普通 YAML config 补丁丢失 Provider 的问题。
