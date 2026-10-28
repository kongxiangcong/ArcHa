# Onboard 状态目录与未知用量恢复验收

日期：2026-10-28。基于 `codex/observer-workbench@5b62cd6`，在本地 `fix/observer-history` 上继续实施；保留上一轮观察器修复。用户上传的 9 文件补丁统一换行后通过 `git apply --check` 并应用，没有覆盖前一轮改动。

## 已完成

- Codex 角色 `codex_home` / `OPC_CODEX_HOME` 配置，优先于继承的 CODEX_HOME；显式目录必须是现有绝对路径。仅修改子进程环境，不复制认证或提权。
- 启动前清理旧 last 回复，保留只读错误诊断；仅启动阶段 OSError 标记 not_started 和已知零 token，已启动但缺 usage 继续保持未知。
- 账本按原未知事件 seq 追加 accounting_reconciled，原事件保留。整批校验、事务补记差额、证据 SHA-256、相同回执幂等、冲突拒绝。
- 对账要求持有项目 writer 锁，且 run 必须是 preparation；不可读取的证据转换为 OPCError。
- onboard --reconcile-usage 只记账，不派发 worker；保留原预算、host 累计量单调性、未解决事件和预算耗尽门禁。
- 补充原补丁未覆盖的旧 ready 边界：后续调用产生未知用量后，直接提交对账也必须退回 pending，重新准备并独立审阅。
- static_check 与 hard_check 只阻断未对账事件；每次准备保留独立 UUID 日志目录和 reviewer 子目录，错误返回包含调用与已入账事实。

实现文件沿用上传清单的 9 个文件：opc/adapters/codex.py、opc/core/worker_config.py、opc/core/ledger.py、opc/scaffold/onboard.py、opc/core/engine.py、opc/cli.py、opc/scaffold/ONBOARDING.md、opc/tests/test_accounting_recovery.py、opc/tests/test_research_loop.py。

## 本轮实际验证

全仓：**290 passed、5 skipped、12 subtests passed**，包括上一轮观察器的 60 项测试。新 accounting_recovery 文件的 9 项测试全部通过；原上传补丁提供 5 项，本轮另加 4 项，覆盖旧 ready 失效、writer/preparation 限制、证据变化、目录优先级与父环境隔离、重试日志保留和具体诊断。

直接相关套件先运行 80 项，再加入前三个补充测试后运行 83 项全部通过；最后一个日志回归与全部现有测试一起在全仓验证中通过。未将上传说明中的旧机器结果计为本轮验证。

```sh
PYTHONPATH=/workspace/work/test-deps python -m pytest -q
python -m opc onboard --help
```

日志：work/accounting-related-tests.txt、work/accounting-full-tests.txt。`git diff --check` 通过，CLI 帮助可见 --reconcile-usage。Linux / Python 3.12.14，测试使用临时项目和模拟 worker 子进程；观察器仍在具有本地网络权限的测试环境中通过，没有重现上传说明中的 TestClient 停顿。

## 使用与边界

按 [ONBOARDING.md](../../opc/scaffold/ONBOARDING.md) 配置已有、可写且认证配置完整的 Codex 状态目录。针对旧未知事件，保持原 task、原预算和可靠累计 host 用量，提交引用项目内真实证据的差额回执；对账后单独重新准备和审阅。

本轮没有调用真实模型，没有配置或读取认证，没有对任何真实项目补记费用、修改历史账本或启用正式执行。不能用模拟子进程测试证明目标机器的真实 Codex 登录、网络或状态目录可写。已有项目的 .opc/runtime 快照仍需按正常更新流程同步，不能通过重建账本或重置预算绕过恢复流程。

本轮限定补丁导出在 work/onboard-accounting-recovery-final.patch；不含上一轮 observer 或前端 diff。
