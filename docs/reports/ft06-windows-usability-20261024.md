# ArcHa FT06 Windows 可用性测试

日期：2026-10-23 至 2026-10-24（Asia/Shanghai）。结果：真实自动迭代达标，原评测独立复测 PASS，makespan 152 → 56。

## 测试目的和边界

用户要求模拟用户，顺序使用 archa-map、archa-task、archa-loop，验证真实自动推进能否跑通；随后明确要求遇到问题修复框架，不采用一次性绕过。输入是用户提供的独立小型工程 ft06-autoloop-smoke.zip，并非 OR-Tools 官方原样 Benchmark。只允许候选改变 workspace/solver.py，原始任务目标 makespan <=59、评价器、grader、tests 保持不变。未调用外部求解器，也未由观察者直接实现 solver。

模拟方向选择、大纲确认和预算已写入测试项目 .opc/research/discussion.md；这些是用户授权的模拟决定，并非额外真人对话。预算为 6 次尝试、1800 秒引擎预算、600000 worker tokens。onboard 的起草耗费由框架另计，不在引擎 run 预算内。此区别属于成本可见性限制。

## 目录

- 原始失败试验：D:/dsh-proj/ArcHa/.tmp/usability/ft06-20261023/
- 修复后工程：D:/dsh-proj/ArcHa/.tmp/usability/ft06-20261024-fixed/ft06-autoloop-smoke/
- 修复后旁路证据：D:/dsh-proj/ArcHa/.tmp/usability/ft06-20261024-fixed/logs/
- 框架隔离工作树：修复后试验目录下 .opc-workspaces/。

重日志与独立 Git 工程均在被忽略的 .tmp/usability/ 中，未混入框架主仓库。原有工作区改动保留；框架修复未提交或推送。

## 阶段记录

1. archa-map：部署本地 runtime、生成单任务地图 R01 及 task.md；Windows 基线五项测试通过，原评测 exit 2，valid=true，score=152。
2. archa-task：独立子代理只调查源码与接入边界；根据 TASK.md 形成简报并通过 brief-check；真实 onboard worker 起草合同。修复后 onboard ok=true，changed_outside_opc=[]，changed_protected_opc=[]，报告 423534 tokens。观察者核对目标、范围、预算、评价器与简报摘要并记录交接。
3. archa-loop：启用执行、只提交已核对接入文件、check 与 preflight 通过。preflight baseline makespan=152、valid=1，两道 gate 为原单测与原评测的冻结适配器。

原评测 exit 2 的语义是合法但未达标，不能直接套用命令门“非零即失败”。onboard 自动生成 .opc/eval/evaluate.py，运行原评测并核对新报告、退出码、status、valid、四个实例结果和目标；仅将一致的 exit 0/2 映射为合法测量。59 仍是终止目标；exit 3 或不一致报告拒绝。原 evaluate.py 未修改。

## 发现与修复

| 问题 | 真实证据 | 通用修复/处理 |
| --- | --- | --- |
| npm codex.cmd 遮蔽原生 CLI，进程层拒绝批处理 | 原试验 onboard-default.json | Windows 默认 worker 优先查找 PATH 中 codex.exe；显式 binary/env 配置仍优先，不放开 shell 包装器限制 |
| 原生旧 npm CLI 0.130.0 不接受 priority 配置，也不支持现有模型 | 原试验 onboard-native-stderr.txt 和 onboard-permitted.json | 默认入口解析选择已有兼容原生 CLI 0.163.0-alpha.11.2，无模型降级或全局配置改写；早期兼容参数尝试未用于最终验证 |
| CLI 启动错误仅显示 codex exited 1，且误算 worker 失败 | 配置失败原件、回归测试 red 输出 | 无 JSON 错误时返回 stderr；会话创建前失败及配置/版本/app-server/schema 错误归 INFRA |
| runtime 暂存目录 ACL 随 rename 保留，沙箱 worker 无法读取 | worker 命令权限错误；logs/acl-before-after.json 中保护 ACL 从 true 到 false | initialize.py 用继承项目 ACL 的唯一暂存目录，校验后移动；已有测试 runtime 用字节相同的副本显式修复继承，旧副本保留 |
| strict plan schema 未要求 exhausted，真实服务拒绝所有专家请求 | run-1461fe60cc2b 中三次 invalid_json_schema，0 model tokens | required 覆盖全部属性；普通计划 exhausted=false；假 worker 回归模拟服务端该项检查；schema 错误不再消耗搜索次数 |
| designer 不知道合同 scratch 路径，临时抑制本地评测报告 | designer-events.jsonl；官方评测独立通过 | 引擎上下文携带 scratch，提示明确生成物可写、不会进候选补丁，禁止临时修改 evaluator；回归检查生成物未进入冠军 |
| 中文 brief 测试夹具用 Windows 默认编码写入，却按 UTF-8 读取 | 首轮全量测试 13 个编码失败 | 测试夹具显式 UTF-8；真实简报生产校验仍严格 UTF-8 |
| 本机无 symlink 创建权限 | 首轮全量测试 WinError 1314 | 保留直接越界路径验证；仅符号链接分支在权限缺失时 skip；junction 回归在正常 Windows 权限下执行 |

CLI 状态数据库在外层受限沙箱中不可写，需要允许宿主控制器使用现有登录、状态目录与网络；这是执行环境授权，未关闭 expert/read-only 或 designer/workspace-write 的角色沙箱。

## 冻结与预算

第一份运行 run-1461fe60cc2b / r0001 保留 paused 状态，其三次协议失败耗时 47.695 秒、0 tokens，solver 无变化。日志通用文字 paused by user 实际是观察者为停止重复框架错误而调用 pause。

修复后显式部署新的 runtime，创建 r0002 和新 run，不原地改旧 revision。新合同仅使用剩余 3 次尝试、1752 秒、600000 tokens。基础评测器摘要前后均为 91a9759c7701ae944349c9ae0ab5c82c7985858acabc87db43eba27eb3db006d。原始源码摘要记录在 logs/original-sha256.json。

## 最终结果

- Run：run-3a23237fadf2；task=t-main；revision=r0002；state=closed；stop_reason=target_met。
- 基线提交：bcd303304a8f4ad0efbb2350341e3ece36ae3f60。
- 冠军提交：0452320f041208dce755e7944f44bd23d98cb038；分支 refs/heads/opc/t-main；未 promote 到 main。
- 真实引擎一轮接纳：makespan 152 → 56，valid=1，改善 63.16%。run 耗时约 190.919 秒、246173 tokens（包含缓存输入计数，费用未知）；剩余 2 次尝试、1561.1 秒、353827 tokens。前序协议失败另计 47.695 秒，总计仍在原授权运行预算内。
- 最终算法：基于输入计算剩余工时、就绪操作与机器冲突集合，五种优先级配合固定随机种子的 10000 次重启，保留最佳合法排程。仅依赖标准库 random，未发现硬编码实例、答案或目标阈值。较大实例性能不在本次验证范围内。
- 冠军相对基线仅 workspace/solver.py 有差异；七个原始冻结文件逐字节等于 zip 内版本，验证记录 logs/champion-audit.json。
- 导出后原样运行 python evaluate.py，exit 0 / PASS / valid=true；四项分数依次 56、55、11、22，耗时 2.5354 秒（单次观察）。五项原单测全部通过。
- 另用独立 checker 验证 12 个生成小实例（含非连续机器编号、重复机器访问、不同作业长度）及两个空输入，全部合法。这是补充检查，不替代原评价器。
- 最终可运行工程：.tmp/usability/ft06-20261024-fixed/deliverable/champion/；归档：同级 champion-source.zip；原报告为 champion/evaluation_result.json。运行记录为 logs/final-report.json 和项目 .opc/local/artifacts/research-project/t-main/run-3a23237fadf2/views/。

设计 worker 的本地自测曾用临时 monkeypatch 抑制报告文件写入，以遵守提示词的过窄改动声明；此操作未进入补丁，官方独立评价与最终直接复测均运行未经修改的评价器并写入真实报告。为修复这一提示缺口，框架随后把合同 scratch 路径传给 designer，明确允许这些生成输出，并要求原样运行检查、禁止 monkeypatch 或抑制报告。该后续提示修复以集成回归验证，已关闭的达标运行不被重写。

## 修复交付与复用

框架修复位于 opc/adapters/codex.py、worker.py、prompts.py、opc/core/engine.py、skills/archa-map/scripts/initialize.py；对应回归在 opc/tests/test_codex_and_config.py、test_dsh_worker.py、tools/tests/test_research_skills.py、test_brief.py。平台说明已更新到 docs/cross-platform.md。没有把 FT06 的指标、目标或算法写进通用引擎。

本机 archa-map、archa-task、archa-loop 已通过 tools/install_research_skills.py 重新安装并保留备份。安装后逐文件核验 runtime 与最终框架源码一致，snapshot SHA-256 为 9e08dba1df9398517d35d74cff4a078ac933ecd73b0f062a62170f10a81ed959；initializer 也与源脚本一致。证据见 logs/skill-install-final.json、installed-verification.json。

用户原先未提交的 README、技能重命名、讨论文档等改动未回滚或整体提交。独立试验工程提交仅用于冻结与候选隔离；框架源码修复仍留在当前工作区供审阅。

## 最终回归结果

对最终源码按测试文件分为三个互不共享临时目录的完整分组执行，所有分组退出 0：47 passed / 2 skipped；58 passed / 1 skipped；40 passed / 1 skipped。总计 **145 passed，4 skipped，0 failed**。日志为 logs/final-suite-0.txt、final-suite-1.txt、final-suite-2.txt。跳过项与本机平台/符号链接权限有关；真实 Windows junction 及 ACL 继承检查已执行。

git diff --check 通过；修复后试验项目主工作树干净，冠军保留在独立分支。最终源码覆盖真实 worker schema 拒绝、启动故障分类、原生入口选择、生成报告路径传递、冻结评价器不可修改、临时输出不进入冠军、runtime ACL 继承、UTF-8 简报以及原有引擎行为。

## 验证范围

这项测试验证一个真实小工程在本机 Windows/Python 3.14 上的接入与优化闭环，不证明任意项目都能自动优化，也不证明所有 CLI 版本/操作系统组合兼容。原包仅四个评测实例和五项测试，通用性仍需源码审阅。完整日志与账本保留供复核。
