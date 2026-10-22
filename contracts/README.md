# OPC 合同与模板索引

当前推荐 **v0.2（2026-10-22）**：见[升级说明](V0.2.md)、[模型](models_v02.py)、[新模板](templates/v0.2/README.md)、[样本](examples/v0.2/)和[Schema](schemas/v0.2/)。它在原合同上补充项目/组件/基线、稳定需求ID、决策分类、可观察行为、关键连接与逐项验证。执行 `python contracts/validate_v02.py` 检查六类新对象与跨对象绑定。

下文保留 **v0.1** 的说明与API语义。新旧版本分目录，不覆盖历史样本；DecisionRequest/JobRecord暂保留v0.1形状，统一生产adapter仍待实施。

日期：2026-10-21。此目录是**通用生产接口提案**，不代表服务已经部署。`examples/gemv_loop` 是单独的受限演示接口；不能把它的简化字段当作已实现本目录全部协议。

- `models.py`：严格 Pydantic 模型，未知字段拒绝，支持生成 JSON Schema。
- `schemas/`：给 Ge、SDK、前端表单和后端共用的六种 JSON Schema。
- `templates/`：用户输入与 Ge 转换清单。
- `examples/`：可解析的合同样本；只有服务校验授权记录、资产、预算和环境后才能下发。

依赖见 `requirements.txt`。本次使用已有 Python 3.14.0 / Pydantic 2.12.5，未安装新包。在其他环境可用独立 venv 安装这些固定版本。

```powershell
python contracts/models.py --export
python contracts/validate_examples.py
```

## 授权和签署不能放在自报字段里

`authorization_ref` 是指向用户授权记录的引用。Ge 不得自己生成一个字符串就当已批准；接纳服务必须核实记录主体、有效期、合同摘要、资源和额度。review_call_id、producer_call_id 同样必须由受信 worker adapter 登记，提交者自报的字段只用于匹配，不能决定身份。

Schema 能检查结构和局部不变量，不能证明：文件存在、权限有效、评价器可信、模型调用独立、预算足够、指标可比。以上是服务层校验。

## 序列化与摘要

文件 SHA-256 对原始 bytes 计算。任务摘要按解析后的合同序列化为 UTF-8 JSON：键排序、紧凑分隔符、保留 Unicode、不允许 NaN/Infinity；生产端要统一数值序列化实现并发布测试向量，跨语言前建议采用 RFC 8785。当前 Python 模板不是 RFC 8785 实现。manifest 包含按 URI 排序的路径、大小、内容摘要与角色；manifest 自身不包含自己的摘要。审查绑定 `(task_id, revision, task_spec_sha256, submission_id, manifest_sha256)`。

Artifacts 必须能取回原件；只有 hash 没有原件为 `EVIDENCE_UNAVAILABLE`。外部路径先解析符号链接和最终绝对路径，再验证允许根目录；不接受 `../`、路径覆盖或 manifest 指向自身。

## API 约定

所有变更命令需认证主体、`Idempotency-Key` 和预期版本。重复 key + 同请求摘要返回原结果；相同 key + 不同摘要返回 `409 IDEMPOTENCY_CONFLICT`。状态并发更新使用 revision CAS，失败返回 `409 STALE_REVISION`。

| 命令 | 输入 | 成功结果 / 关键拒绝 |
| --- | --- | --- |
| `POST /tasks/drafts` | MRD、材料引用 | TaskSpec 草案 + DecisionRequest，不下发 |
| `POST /tasks` | TaskSpec + 授权记录 | task_id、revision、state / 422 INVALID_SPEC、409 NEEDS_DECISION |
| `GET /tasks/{id}` | task_id | 执行/接纳/候选状态、事件游标、预算、下一动作 |
| `POST /tasks/{id}/revisions` | 基准 revision、新合同、用户决定 | 新 revision；旧提交保持历史，标记依赖失效 |
| `POST /tasks/{id}/pause` | dispatch_stop 或 drain | 请求已登记；有活 job 时不是 paused |
| `POST /tasks/{id}/resume` | 预期 revision | 先 reconcile，再继续；UNKNOWN_JOB 不重发 |
| `POST /tasks/{id}/cancel` | 取消理由 | cancel_requested；收到后端确认才 cancelled |
| `POST /attempts/{id}/submissions` | manifest + Submission | server 冻结并重算摘要 / 409 CONTENT_CHANGED |
| `POST /submissions/{id}/reviews` | adapter 受限凭证 + ReviewDecision | 回执，待接纳 / 403 SELF_REVIEW、409 STALE_REVIEW |
| `POST /decisions/{id}/resolve` | 用户主体、选项、预期 revision | 决策事件；预算或验收变化生成新任务版本 |
| `GET /tasks/{id}/events?after=seq` | 最后事件序号 | 单调 seq 的事实记录，不从聊天推算进度 |

`accepted` 只有接纳服务可写。reviewer 推荐 accept，服务仍需验证两个轴、调用身份、当前摘要、硬门、覆盖范围和合同版本。任何 worker 自写 `accepted.json` 都不产生授权。
