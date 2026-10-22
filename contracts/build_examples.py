"""Generate illustrative protocol payloads. These are NOT real run receipts."""
import hashlib
import json
from pathlib import Path

from models import export

ROOT = Path(__file__).parent


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write(name: str, data: dict) -> None:
    (ROOT / "examples" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    (ROOT / "examples").mkdir(exist_ok=True)
    source = ROOT / "templates/MRD-SPEC.md"
    source_ref = {"uri": "contracts/templates/MRD-SPEC.md", "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "locator": "SPEC / template only"}
    # Placeholder references are explicitly unresolved; draft may not dispatch.
    unresolved = {"uri": "template://replace-with-frozen-evaluator", "sha256": "0" * 64, "locator": "UNRESOLVED"}
    task = {
        "schema_version": "opc.taskspec.v0.1", "task_id": "gemv-row-block-proposal", "revision": 1,
        "parent_task_id": None, "task_kind": "optimize", "objective": "在冻结GEMV访存模型下搜索合法行分块调度，保存失败与独立复核证据",
        "source_requirements": [source_ref], "scope_in": ["生成行分块调度", "整数GEMV功能验证", "模型流量比较"],
        "scope_out": ["真实硬件PPA", "修改参考与评价器", "外部付费模型"],
        "deliverables": ["候选代码", "全部实验原件", "双轴审核", "条件结论"], "inputs": [],
        "research_unknowns": ["给定容量下最佳已测试tile"], "open_decisions": ["示例占位引用必须替换为可访问冻结资产；运行授权由服务解析"],
        "acceptance": {"evaluator": unresolved, "workloads": [dict(unresolved, uri="template://replace-with-workloads")],
            "hard_gates": ["整数功能与独立参考一致", "累加器容量约束通过", "manifest完整且当前", "两个审核轴均通过"],
            "metrics": [{"metric_id": "element_transfers", "unit": "element", "direction": "minimize", "evidence_level": "analytical", "aggregation": "sum across frozen cases", "target": None}],
            "required_review_axes": ["standards", "spec"], "accept_conditional": True, "evidence_ceiling": "analytical"},
        "budget": {"max_attempts": 6, "max_review_calls": 8, "max_wall_seconds": 120,
            "model_usd_cap": 0.0, "model_tokens_cap": 0, "max_concurrent_jobs": 1, "unknown_price_policy": "block", "inflight_at_limit": "drain"},
        "permissions": {"readable_roots": ["examples/gemv_loop"], "writable_roots": ["runs/gemv-proposal"],
            "frozen_refs": [unresolved], "allowed_tools": ["registered-offline-gemv-runner"], "network": "disabled", "network_allowlist": [], "publish": False, "modify_harness": False},
        "stop_rules": ["实验次数耗尽", "墙钟耗尽", "用户暂停或取消", "无新合法候选"], "authorization_ref": None,
        "domain": {"adapter": "gemv-row-block", "example_only": True, "M": 8, "K": 64, "accumulator_capacity": 4}}
    write("TaskSpec", task)
    binding = {"task_id": task["task_id"], "task_revision": 1, "task_spec_sha256": digest(task)}
    artifact = {"uri": "template://not-an-execution-receipt", "sha256": "0" * 64, "size_bytes": 0, "media_type": "application/json", "producer_job_id": "TEMPLATE-job-1"}
    write("ExperimentPlan", dict(binding, schema_version="opc.plan.v0.1", plan_id="TEMPLATE-plan-1", parent_submission_id=None,
        evidence_refs=[], hypothesis="增加共享输入的行块可减少输入读取", competing_explanation="收益可能来自漏算尾块",
        change="row block 1 -> 2", controlled_variables=["输入、数值语义、评价器、累加器容量"], falsification="功能不一致或模型总流量不降则否定",
        measurement_commands=[["registered-offline-gemv-runner", "--tile", "2"]], expected_artifacts=["kernel.py", "measurement.json", "review.json"],
        predicted_model_usd_upper_bound=0.0, predicted_wall_seconds=10))
    write("Submission", dict(binding, schema_version="opc.submission.v0.1", submission_id="TEMPLATE-submission-1", attempt_id="TEMPLATE-attempt-1",
        plan_id="TEMPLATE-plan-1", producer_call_id="TEMPLATE-runtime-issued-call", manifest_sha256="0"*64,
        artifacts=[artifact], claims=[], limitations=["仅结构示例；没有真实运行原件"], failed_checks=[], environment_ref=artifact))
    axis = {"verdict": "inconclusive", "findings": ["模板缺少真实原件"], "checked_artifacts": [artifact]}
    write("ReviewDecision", dict(binding, schema_version="opc.review.v0.1", review_id="TEMPLATE-review-1", review_call_id="TEMPLATE-reviewer-call",
        submission_id="TEMPLATE-submission-1", manifest_sha256="0"*64, standards=axis, spec=axis,
        recommended_disposition="blocked", conclusion="结构示例，不构成审核结论", accepted_claims=[], unknowns=["实际执行与身份待核验"]))
    write("DecisionRequest", {"schema_version": "opc.decision.v0.1", "decision_id": "TEMPLATE-decision-1", "task_id": task["task_id"],
        "expected_revision": 1, "reason": "resource", "question": "首个真实部署使用哪个已经可用的执行环境？",
        "options": ["现有受控主机", "已有隔离容器"], "recommendation": "先选择现有且可核查权限的环境", "blocked_actions": ["真实agent adapter派发"]})
    write("JobRecord", dict(binding, schema_version="opc.job.v0.1", job_id="TEMPLATE-job-1", attempt_id="TEMPLATE-attempt-1", role="experiment",
        idempotency_key="TEMPLATE-task1-attempt1-experiment", input_digest="0"*64, state="intent", backend_job_id=None, runtime_call_id=None,
        reserved_model_usd=0.0, actual_model_usd=None, result=None, reconcile_note="尚未派发"))
    export(ROOT / "schemas")


if __name__ == "__main__":
    main()
