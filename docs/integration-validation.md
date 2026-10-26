# 项目接入与合同 v0.2 验证记录

日期：2026-10-22。范围是通用项目的接入设计、元数据初始化、实验路径计算和合同追踪校验。本轮没有向真实 openTPU 仓库安装 OPC，没有运行 GSD、真实模型调用或 EDA 作业。

## 1. 结论与可用入口

本轮已实现 **ProjectConfig/ComponentConfig、v0.2 任务—计划—提交—审核合同、八份人读模板、接入骨架与路径 CLI**。两个不同源码结构的演示项目实际初始化成功，源码 SHA-256 均未变；全部配置仍为 disabled/unconfigured。

合并测试 **30 passed、1 skipped**；新合同的 **6 份样本、6 份 schema、关联草案**通过，**10 个字段/模型反例与 7 个跨对象反例**被拒绝。旧 v0.1 的 6 份样本、6 份 schema 与 4 个反例继续通过原校验。两项独立审核发现的 P2 均已修复，并经独立定向复验关闭。

- 规范：[项目接入与目录规范](design/OPC%20项目接入与目录规范.md)。
- 合同：[v0.2 升级说明](../contracts/V0.2.md)、[模板入口](../contracts/templates/v0.2/README.md)。
- 可执行例子：[接入工具与两项目示例](../examples/project-onboarding/README.md)。
- 原有优化闭环：[GEMV 验证记录](validation.md)，保持 v0.1 历史归属，没有被改名包装成 v0.2 集成验收。

## 2. 复用依据与版本

| 来源 | 固定版本 | 本轮使用范围 |
| --- | --- | --- |
| openTPU | `506e81b1d297e22739dab5ecaeee684493d5c720` | 重读配置、候选工作区、实验日志、缓存与保存/清理代码；采用分离原则，不复制特定 RTL 布局或 force cleanup |
| open-gsd/gsd-core | `812ddb5feb357ebf702b7f48c3e915a8ce4da384`，package 1.18.0 | 重读模板与 coverage/onboard/fingerprint 等实现；采用稳定 REQ、决策边界、行为/产物/连接、覆盖与交接结构 |

逐项主来源链接见 [openTPU 核查](research/project-integration.md) 与 [GSD 核查](research/gsd-contracts.md)。GSD 中文模板在本项目重写；未安装 GSD 或增加第二个 Master。上游代码实现、OPC 设计、当前本机验证三个层次分别陈述。

## 3. 实际验证与原件

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 接入工具 + 旧 GEMV 合并测试 | 30 pass、1 skip，25.31 秒 | [JUnit](evidence/v02-tests.xml) |
| v0.1 合同兼容 | 6 样本/6 schema 同步；4 反例拒绝；未授权草案不能派发 | [命令记录](evidence/v02-checks.json) |
| v0.2 合同 | 6 样本/6 schema 同步；关联草案合法；10+7 反例拒绝 | 同上 |
| Ruff | contracts、路径工具及其测试通过 | 同上 |
| Mypy | contracts 6 文件、路径工具 1 文件通过 | 同上 |
| 两项目源码与配置复算 | 源码与接入前后摘要一致；配置符合 ProjectConfig 且 disabled | [复算结果](evidence/v02-fixture-recheck.json) |
| 独立产物绑定复验 | 原绕过拒绝；完整绑定正例通过；missing/unverified 草案合法 | [原件](evidence/contracts-v02-review/artifact-binding-recheck.json) |
| 独立路径冲突复验 | 文件祖先/叶子冲突拒绝；正常路径只预览不创建 | [原件](evidence/integration-layout-review/path-types-recheck.json) |
| 旧运行原件核对 | 正式 GEMV 冻结 domain/contract 与 8 轮 manifest 摘要一致 | [原件](evidence/contracts-v02-review/legacy-read-check.json) |

交付前还检查了 39 份 Markdown 中的 85 个本地链接，未发现缺失目标（[检查记录](evidence/v02-doc-links.json)；计数为加入本句之前的快照，不包含远端链接可用性）。

两个接入 fixture 分别为 `src/pipeline.py` 和 `rtl/identity.sv`。它们证明接入无需统一源码目录，不证明编译器或 RTL 的领域功能正确。compiler 使用默认本地证据根，RTL 使用外部证据根；各生成两次 attempt 的路径预览，未建立实际实验工作区。

合并测试中唯一跳过项是实际符号链接越界用例：当前 Windows 环境不允许测试创建链接。该逻辑经过源码审查，但真实符号链接、junction 和跨平台权限隔离未完成验收。测试还输出两条现有依赖 warning：Python 3.14 下 LangChain 引入 Pydantic V1 的兼容警告，以及 LangGraph serializer 的未来默认值变化警告；未将本次通过扩大为生产环境兼容保证。

审核原始探针产生于 `.tmp/`，现按字节归档到本报告的 `evidence/`；[归档清单](evidence/v02-review-archive.json)记录来源、目标和 SHA-256。这里的正例 ArtifactRef 为结构占位，不是真实 job 回执或已认证证据。

## 4. 独立审核关闭项

| 审核 | 发现 | 修复和定向复验 |
| --- | --- | --- |
| [目录与接入审核](reviews/review-integration-layout.md) | 生成子路径的普通文件祖先仍会被当作目录返回 | 对每一级现存父路径及目录/文件叶子校验；补 4 类冲突测试；独立复验原反例与正常路径 |
| [合同审核](reviews/review-contracts-v02.md) | Plan 的预期产物 ID 没有映射到提交的具体原件 | 增加 `artifact_bindings`；计划项显式 present/missing，present 必须属于提交原件，REQ pass 必需产物齐全；同步 SUMMARY/VERIFICATION 模板 |

当前范围没有未关闭的 P1/P2。审核由不同子 agent 执行，但共享主机权限，因此这里只能说明审查分工独立，不能说明生产 reviewer 的权限隔离已落地。

## 5. 复现命令

从 `D:/dsh-proj/Ge` 执行，依赖沿用 [GEMV 环境说明](../examples/gemv_loop/README.md) 与 [合同依赖](../contracts/README.md)。每次复跑使用新的 basetemp 和 JUnit 文件名，保留已有原件：

```powershell
$env:TEMP = 'D:/dsh-proj/Ge/.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
python -m pytest tools/tests examples/gemv_loop/tests -q --basetemp .tmp/pytest-v02-rerun-001 --junitxml docs/evidence/v02-tests-rerun-001.xml
python contracts/validate_examples.py
python contracts/validate_v02.py
python -m ruff check contracts tools/project_layout.py tools/tests/test_project_layout.py
python -m mypy contracts --follow-imports=silent
python -m mypy tools/project_layout.py --follow-imports=skip
```

## 6. 尚未实施与下一步验收

目录规范描述了生产目标；当前 CLI 只做新 `.opc` 初始化与路径计算。它不创建 ledger、真实任务、worktree 或 job，不冻结候选，不运行 adapter/agent，不做预算结算、身份鉴权、对象存储写保护、GC 或部署。已有 `.opc` 的 read/import/升级仍需实现。

下一实现切片应让**一个真实目标项目的一个组件**通过登记、基线快照、受限命令执行、产物冻结、独立审核与恢复，使用本版完整追踪链。先验证单轮成功/失败和停止恢复，再接自动多轮；无需先扩充公司层级或复制更多模板。v0.1 JobRecord/DecisionRequest 升级、artifact resolver 和服务侧授权/摘要核验属于这个切片的必要工作。
