# 04: 独立审核逐项覆盖必需需求

**What to build:** 一次独立审核能够针对明确交付候选覆盖多个需求，逐项给出判断及依据；遗漏、失败或证据不足的必需项不能被总体“通过”掩盖。依据 [S4 规格](../spec.md)。

**Blocked by:** 03 — 固定探索交付对象与版本

**Status:** resolved

- [x] 扩展既有审核返回，使判断按需求身份关联必要依据或缺口，并由 Engine 逐项消费；具体字段形式保持最小，不新增审核服务。
- [x] 可区分通过、不通过、证据不足和未覆盖；仅 REQ-1 获得依据时，整体 accept 不使必需 REQ-2 自动通过。
- [x] 缺失的可选项不被提升为必需项；真实阻塞发现仍说明原因，整体意见不能绕过程序检查或必需测量/复现。
- [x] 只按契约需要调用 Reviewer，采用未参与候选制作的新只读上下文，不强制不同模型，不拆成每项一个 Worker，不新增逐轮审核。
- [x] 审核意见绑定实际对象、版本及范围；材料截断或原件缺失导致依据不足时不能声明完整覆盖，后续主张版本不继承通过。
- [x] 探索有效反例可形成否定答案；契约要求边界解释而未提供时不通过，补齐并覆盖后可通过。允许未决与阻断核心问题的未知按原契约区分。
- [x] 调用失败、无有效返回与已完成审核的否定判断分别保留，供后续失败回流使用；既有可靠回执重放不重复调用或计费。
- [x] 报告与只读观察按需展示各需求判断、依据和缺口；通过受控 Reviewer 检查实际输入/输出及放行结果，完成相关回归并移除整体 accept 批量放行路径。


## Comments

2026-11-01 实施完成（80791f9）：Reviewer 一次返回按 requirement ID 关联的 status（met / not_met / insufficient_evidence / not_covered）、evidence 和 gap。Engine 验证具名唯一覆盖，省略必需项为 not_covered，met 无依据为 insufficient_evidence；非 met 同时没有依据与具体 gap 时保留原回复并标为无效审核输出。总体 accept 不再批量放行。程序检查失败不能被模型 met 覆盖；模型发现的必需语义阻塞也不能因程序通过而丢弃。可选项缺失仍仅警告。TaskSpec 在外部输入处要求需求 ID 唯一且非空，避免覆盖歧义。

复用已有一次新只读 Reviewer 调用及可靠回执，不增加逐轮审核或每项 Worker。共享 Reviewer prompt 明确 JSON 形状、逐项覆盖、缺失/截断必要证据、否定答案、边界解释与允许未知的契约范围；DSH 不依赖其未消费的 output schema。JSON/Markdown 报告和 observer 同时显示逐项判断、依据、缺口与原报告链接。调用失败/无效返回与已完成的否定或证据不足判断保留不同事实。

验证：本票最终专项 `test_requirement_review.py` 10 passed；覆盖 overall accept 遗漏第二必需项、空依据、optional、程序检查与 Reviewer 阻塞的双向组合、反例否定后补齐边界、不同失败事实、单次 DSH 假 CLI 多需求审核及回执重放/7 token 计量、歧义 ID 拒绝、missing/truncated 必要原件。受影响终验/target/optional/旧选定成果回归组合 17 passed；candidate/history/Reviewer 可靠回执与未知状态专项 15 passed。开发中 DSH fixture 曾将 reviewer 错放 task.workers，被已有边界拒绝；改为 local worker 配置后复跑通过。未启动正式研究考试；仅假 DSH CLI 验证框架协议，不宣称真实 DSH/模型能力已验证；HTTP fixture 未纳入本票验收。
