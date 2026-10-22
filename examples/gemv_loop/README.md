# OPC 离线 GEMV 闭环技术验证

本例已经实际运行。它验证确定性状态机、真实数值执行、固定提交审核、反馈搜索、预算和跨进程恢复；不验证 LLM 自主科研，也不验证真实硬件性能。

## 实际复用与实现范围

- 复用 **LangGraph 1.0.9** `StateGraph` 做 `expert → design → experiment → freeze → review → decide → expert` 路由。
- 复用 Python 标准库 SQLite 做权威状态、事件、作业意图与回执；**没有使用 LangGraph checkpointer**。每个节点结束后提交应用状态，再次启动从持久 `phase` 进入图。
- `expert` 是读取上一轮审核与指标的确定性搜索策略；`design` 是 Python kernel 模板生成器，均不是模型调用。
- 实验与 verifier 是实际分别启动的 Python 子进程。verifier 重跑固定代码，使用无分块的内积 golden，并核对访问计数与模型公式。
- SQLite 中由父控制器生成的调用 UUID、PID、命令和回执证明实际有不同子进程。它不构成用户/操作系统权限隔离，也不是独立 LLM reviewer。
- `contract.json` 是此例的冻结简化领域合同，**尚未接入仓库 `contracts/` 的通用生产协议或 Argus**。

`loop.py` 负责运行控制，`domain.py` 负责冻结领域规则。候选只有 `candidate.py`；父控制器才写 ledger、manifest 和决定。生成代码可被 `exec` 执行，但 AST 检查不是安全沙箱；不要向本例提交不可信代码。生产版需要容器/OS 账号、只读挂载和受限审核端点。

## 可复跑命令

在项目根目录 `D:\dsh-proj\Ge` 执行；使用一个不存在或为空的新 run 目录：

```powershell
python examples/gemv_loop/loop.py run --run-dir examples/gemv_loop/runs/my-run --max-attempts 8 --pause-after 2
python examples/gemv_loop/loop.py resume --run-dir examples/gemv_loop/runs/my-run
python examples/gemv_loop/loop.py status --run-dir examples/gemv_loop/runs/my-run
```

`run` 拒绝覆盖非空目录；`resume` 从安全边界继续。`--pause-after` 是累计已完成轮数，不是后台实时暂停按钮。`status` 不派发工作，但会重新导出 `report.json` 和 `events.json`。

审核子进程明确失败且回执已落库时，可以只重试审核，最多两次额外调用：

```powershell
python examples/gemv_loop/loop.py retry-review --run-dir examples/gemv_loop/runs/my-run
```

未知 `intent/running` 作业恢复时进入 `blocked`，不会盲目重派，也不能用 `retry-review` 绕过。此例没有远端作业认领或人工对账 API；生产适配器必须补齐。

依赖版本见 `requirements.txt`，本次直接使用已有本机环境，没有安装模型后端。运行环境为 Python 3.14.0。导入依赖会产生 Pydantic V1/3.14 兼容警告和 LangGraph serializer 的未来默认值警告；本例未使用 V1 数据模型或 checkpoint serializer，当前测试通过，生产部署仍需独立锁环境和兼容性测试。

## 领域合同与探索

固定工作负载 `(M,K)`：`(1,1), (5,7), (17,13), (32,64)`。权重与输入由固定整式生成，包括负数和零。运算使用 Python 精确整数，不模拟定点溢出、量化和浮点舍入。

候选沿 M 维分块；每个 K 步加载一个输入标量，复用于 tile 个输出行。模型假设没有 cache，权重每项加载一次，输出最终写一次，并保留 tile 个累加器。累加器上限固定为 12。

每个形状的标量传输量为：

```text
T(M,K,b) = M*K + ceil(M/b)*K + M
          权重读    输入读       输出写
```

实际执行通过加载回调统计权重读和输入读；输出写按最终输出元素数计数。reviewer 另用上式核对计数。指标是**标量元素数**，不是字节数、运行时间、DRAM 周期、带宽、能耗或面积。

规则专家先运行 `b=1` 基线；无资源失败时倍增，出现资源失败后在已通过与失败的 tile 边界间二分。它读取真实结果，没有预填指标或固定“获胜者”。这是小范围搜索策略，不能泛化成能自动发现开放科研方向的专家。

验收顺序：Standards AST 操作范围检查 → 验证唯一顶层 `TILE` 为正整数常量、未被重定义/遮蔽且与冻结计划参数相等 → Spec 精确输出/传输模型/累加器约束 → 同一冻结提交的实验与复核指标一致 → 比较指标、保留严格改进。不能确定的 tile 声明直接拒绝。Standards 只覆盖这个原型的有限操作规则，不是完整工程可维护性或因果推理审核；资源解释只适用于本例模板语义，不能当作任意 Python 程序的资源证明。

每个尝试在设计/实验前消耗 1 次预算。功能失败、资源失败仍消耗；审核重试另有最多 2 次上限。没有模型调用，所以没有模型账单；此例没有实现生产的美元、token、wall-time 或并行预算预留。

## 证据与恢复语义

每轮 `attempt-NNN/` 包含 `plan.json`、`candidate.py`、`experiment.json`（命令、原始 stdout/stderr、退出码与调用身份）、`manifest.json`、`reviewer-0.json`、`decision.json`。重试保留 `reviewer-1/2.json`。

manifest 覆盖计划、候选代码、实验原件、合同 hash 与领域 evaluator 源码 hash。其 digest 写入 SQLite。run 根目录保存该次 `domain.py` 原件快照；检查时同时核对保存原件和当前运行源码，不能用只有摘要而找不到原件的记录代替复核。review 前和接纳前均重算，避免把旧审核给新 bytes 放行。`status` 对历史提交再次验证；`best` 保留历史事实，`acceptance_currently_valid=false` 表示当前产物已经不能沿用该接纳，`invalid_submissions` 列出损坏项。

作业在启动前写入 intent；回执入库后才推进工作。若回执完成但 phase 尚未提交，恢复会从账本取回同一个回执，不再启动同一 job。若在 intent 后崩溃而无法判断是否完成，则保守阻塞。它不宣称通用 exactly-once。

边界：单个控制器、单机短作业；无后台 daemon、租约、多控制器并发、远端取消、独立签署服务、不可写对象存储、held-out 工作负载、完整项目 DAG 或真实模型 adapter。SQLite 和源文件对同一用户可写，hash 只能检验内容一致性，不能对抗拥有相同文件权限的攻击者。研究结论仅限固定四形状与模型。

## 验证

```powershell
$env:TEMP = 'D:/dsh-proj/Ge/examples/gemv_loop/.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
python -m pytest examples/gemv_loop/tests -q --basetemp examples/gemv_loop/.tmp/pytest-new
python -m ruff check examples/gemv_loop/loop.py examples/gemv_loop/domain.py examples/gemv_loop/tests
python -m mypy examples/gemv_loop/loop.py examples/gemv_loop/domain.py --ignore-missing-imports --follow-imports skip
```

12 个行为测试覆盖：尾部漏算、实际 tile=13 误报计划 tile=12、bool/表达式/重复 tile 声明、反馈搜索/失败预算、不同进程暂停恢复、未知在途阻塞、审后篡改、历史接纳失效、审核失败和仅重试审核、错误候选不能获胜。测试使用仓库内临时目录，以避开本机 sandbox 默认 TEMP 创建失败。

本次结果见 [RESULTS.md](RESULTS.md)；审查修复后的机器证据见 [最终报告](runs/final-reviewed-20261021/report.json)、[暂停时报告](runs/final-reviewed-20261021/paused-report.json)、[JUnit](runs/tests-reviewed.xml)。
