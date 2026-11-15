# 02: 通过通用命令运行真实 Worker

**What to build:** 用户为两个角色配置命令或 preset 后，可从部署入口执行实际子进程，持续查看输出，并在错误或超时时得到明确失败。

**Blocked by:** 01：部署并跑通专题单步流程

**Status:** resolved

依据：[父规格](../spec.md)、[现行执行协议](../../../opc/README.md)、[架构决策](../../../docs/adr/0001-topic-workspace.md)。原开发方案及文件清单通过 Git 查找。

**范围与归属：** 负责通用 Worker、配置解析、默认配置、命令模板和流式日志的替换实现；精简复用跨平台进程树能力。旧特定 CLI 适配器的最终删除由 09 负责。

- [x] 项目配置优先，缺省使用随运行时分发的默认配置；未知 preset、旧字段、错误类型、非法模式、非正超时及不可用模板变量在调用前明确报错。
- [x] 命令为非空字符串 argv 数组，不隐式拼接 shell；工作目录、专题及各动作的输入输出变量按方案提供，自定义脚本不使用模型变量时无需填写模型。
- [x] 从已部署 CLI 验证 stdin/file 两种输入；Expert 只用文件输出，Executor 可显式选择文件或 stdout，文件模式不自动回退到 stdout。
- [x] Worker 保留调用方已准备的状态草稿；只在零退出、未超时且必需输出非空白时返回可提交成果，错误日志不作为正文。
- [x] 非零退出但有输出、空白输出、缺少输出与超时均失败且不推进下一角色、不自动重复调用。
- [x] 子进程运行中即可读取 stdout/stderr 日志；中断和失败保留已有输出，同轮同角色重试可覆盖旧日志。
- [x] 启动后登记失败、异常、超时和正常结束均完成归属进程树收尾；确认后代结束后才能允许发布成果，沿用适用的 POSIX 与 Windows 能力。
- [x] 用小型真实子进程从 CLI 验证输出、超时和后代清理；默认 preset 参数以实际可用 CLI 的帮助核实，不默认绕过其权限机制，必要资源随部署同步。


## Answer

通用 Worker 使用严格的新配置、argv 模板、项目配置优先及随部署分发的 Codex 默认 preset；支持 stdin/file 输入与 Executor stdout 正文。模型参数仅按配置使用。Expert 状态草稿由引擎准备并保留。stdout/stderr 实时写入日志，失败和超时不提交，重试不误用旧结果。

复用 Process 生命周期，修复启动登记失败遗留后代的问题，并在发布前确认进程树已结束。Linux 排除不能再写入的僵尸进程；Windows 使用 Job 活跃进程计数。旧适配器保留至 09。

TDD：部署后真实命令测试先失败，再实现；另外复现并修复“失败结果被下次空输出误发布”和“登记失败后代继续写入”。验证：`/tmp/archa-results-venv/bin/python -m pytest opc/tests/test_topic_cli.py opc/tests/test_topic_process.py opc/tests/test_platform.py -q` → **56 passed, 3 skipped**（Windows 专属检查在 Linux 跳过）。覆盖部署资源、配置错误、stdin/file、日志实时可读、非零/空白/缺失/超时、重试及正常/超时/登记失败后的后代收尾。

实际 `codex exec --help` 已核实 `--ephemeral`、`--skip-git-repo-check`、`-C`、`-s workspace-write`、`-o` 和 stdin `-`。25 秒上限的最小真实调用立即退出 1：`failed to initialize in-process app-server client: Read-only file system (os error 30)`；当前环境限制导致无法验证模型返回，未绕过权限机制。未安装 Claude，未提供未经核实的 Claude preset。
