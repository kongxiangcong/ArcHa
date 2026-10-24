# opc：通用自动迭代引擎

把一个“能跑通基线”的项目接进来，给一个方向，引擎就会循环：专家提假设 → 设计者改代码 → 冻结的评测门打分 → 确定性接纳 → 反馈下一轮，直到达成目标、预算用完、搜索枯竭或被暂停。核心代码不含任何领域知识；领域只通过 `.opc/` 下的配置和脚本接入。

## 使用

支持原生 Windows 与 Linux，要求 Python ≥ 3.10 和 Git。Windows 安装后使用 `python -m opc` 或 `opc`；平台配置、进程清理和限制见 [跨平台运行](../docs/cross-platform.md)。

```bash
export PYTHONPATH=/path/to/ArcHa          # 或 pip install -e ArcHa，得到 `opc` 命令
cd your-project                           # 必须是 git 仓库，基线已提交
python3 -m opc init -p . --apply          # 生成 .opc/ 模板与 ONBOARDING.md（只写 .opc/）
python3 -m opc onboard -p .               # 可选：codex 按指南起草合同，越界改动即失败
# 人工审合同 → git add .opc && git commit → project.json 里 execution_enabled=true
python3 -m opc check     -p . --task t-xxx   # 静态检查：合同、评价器是否已提交、可改范围
python3 -m opc preflight -p . --task t-xxx   # 在基线上真跑一遍门，确认能出数字
python3 -m opc run       -p . --task t-xxx --direction "先压延迟，面积不许涨"
python3 -m opc status|pause|stop|report -p . --task t-xxx
python3 -m opc promote   -p . --task t-xxx --confirm 2 [--review codex] [--apply main]
```

合同改了（新 revision）要 `run --new-run`，可用 `--base opc/t-xxx` 从上一轮 champion 接着跑。champion 在分支 `opc/<task>`；用户检出的分支只有 `promote --apply` 才会快进。

接入写法见 [scaffold/ONBOARDING.md](scaffold/ONBOARDING.md)（`opc init` 会把它拷进项目）。

四个模型角色的本机配置在 `.opc/local/workers.json`，由 init 生成，Git 忽略。
每个角色独立填写 `model`、`reasoning_effort`，优先于该角色的任务合同；null/省略表示继承。
reviewer 不再继承 expert，onboard 也会读取独立设置。DSH 覆盖需同时提供 provider 和 model。
新项目默认 expert、designer、reviewer、onboard 全部使用 `gpt-6.1-sol / medium`；
已有配置不覆盖。
详见 [worker 环境配置](scaffold/ONBOARDING.md#独立的-worker-环境配置)。

## 结构与接缝

| 模块 | 职责 | 替换点 |
| --- | --- | --- |
| `core/engine.py` | 主循环、停止条件、预算、恢复、视图 | 无（唯一控制者） |
| `core/ledger.py` | SQLite 唯一权威记录，跨平台单写入锁，intent 先写 | — |
| `core/platform.py` / `core/windows.py` | 文件锁、进程树生命周期、可移植路径 | POSIX / Windows |
| `core/workspace.py` | 从 champion 提交切 worktree、sandbox、补丁、CAS 移 ref | — |
| `core/accept.py` | 缺指标即拒、约束、噪声下限、冻结规则文件 | 任务里 `acceptance.rule` |
| `core/promote.py` | 证据链、复测、需求 check、可选独立审核、快进 | — |
| `domain.py` + `domains/command.py` | 领域接口；默认实现＝命令门 + metrics.json | 组件里 `adapter: path.py:Class` |
| `adapters/codex.py` / `dsh.py` / `scripted.py` | worker：codex CLI、DeepSeek Harness headless，或确定性策略 | 任务里 `workers` |

依赖单向：`core` 只经 `domain.load_domain` 和 `adapters.worker.make_worker` 两个工厂拿到领域与 worker（promotion 的可选审核直接用同一套 worker 适配器），不出现任何指标名、工具名或领域路径；领域差异全在项目的 `.opc/` 里。

## openTPU 的教训落在哪里

| openTPU 踩过的坑 | 引擎里的机制 |
| --- | --- |
| 候选改了测试/评分脚本拿高分 | 只取 editable 范围内的补丁，套到干净的 champion 树上跑冻结门；越界即 `sandbox_violation` |
| 缓存/软链/构建产物污染评测 | 每次评测新切 worktree，scratch 路径不进补丁与 digest；缓存仅 `deterministic: true` 且按内容+评价器+工具链 key |
| 评价器或工具版本悄悄变了，新旧数字混比 | 测量带 evaluator/toolchain digest，不一致不比较；工具链变化当场重测 champion |
| 指标缺失被当成“没变坏”放行 | 缺指标、空 metrics 一律拒绝（openTPU 自己的 accept 对空 dict 返回接受，包装规则补上） |
| 环境故障被算成候选失败（或反过来） | 退出码约定 0/75/77/其他，由项目脚本自己分类；INFRA 不计搜索次数，连续 INFRA 即 blocked |
| 进程崩溃后 champion 与记录不一致 | ledger 先写 intent 再 CAS 移 ref，恢复时按 intent 对账；ref 被外部移动则拒绝运行 |
| 额度耗尽后空转烧预算 | 先申请后花费，codex 必须设 `max_tokens`；usage limit 判 INFRA 立即 blocked |
| 噪声里的“提升” | 收益须超过 `max(min_rel_gain, noise_k×极差/|champion|)`；promote 可 `--confirm N` 复测 |

## 已验证

- 单元/失败注入测试 56 个（`python3 -m pytest opc/tests`），含假 codex 与假 dsh：正常、作弊越界、额度耗尽、token 预算、onboard 越界、合同未知字段、审核缺 verdict 即阻塞。
- **真实 dsh 闭环已跑**（与 codex 相反，dsh 不需要等额度恢复）：在玩具项目上专家提出 x=7、设计者改 `params.json`、冻结门打分，loss 17→1，一轮 `target_met`，72556 token 计费，`promote` 走通。
- PIM 模拟器（[examples/pim-emulator](../examples/pim-emulator/README.md)）：参数搜索，延迟 96048→54596 ns（r0002 续跑到 45497），溢出候选判 broken，约束违反被拒，目标 40 µs 未达成如实报告。
- openTPU（[examples/opentpu-otpu-coll](../examples/opentpu-otpu-coll/README.md)）：真实 Verilator lint + Yosys 综合，openTPU 自己的 accept 规则；只加注释判 no_gain，语法错误判 broken。两个领域都没有改核心代码。

## 尚未完成

- 真实 codex 闭环未跑：本机额度到 10-27 才恢复，codex 路径目前只由假 codex 验证。
- 真实 dsh 闭环已验证，但样本只有一个玩具任务；它还没有在 RTL/模拟器上跑过。
- dsh 审核常回一份 markdown 评审而不是 JSON。适配器只接受带 `verdict` 键的 JSON，散文回答判为「审核不可用」并阻塞晋升——宁可挡住，不可放行。要稳定 verdict 需在冻结的审核提示词里强化输出格式。
- 隔离只靠 git worktree + codex 沙箱 + 事后 sandbox 检查，没有 OS 级隔离（容器/用户）。
- 串行执行（每次一个候选）。
- 内置 `param_search` 是坐标搜索，会停在局部最优；更强的搜索应作为策略插件接入。
- Ge 统一入口未实现；`onboard` 只起草合同，不替代人工审核。

