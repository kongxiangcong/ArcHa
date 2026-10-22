"""Generate v0.2 DRAFT samples. No payload here is an execution receipt."""
import hashlib
import json
from pathlib import Path

from models_v02 import MODELS, TaskSpecV02, export

ROOT = Path(__file__).parent


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def main() -> None:
    folder = ROOT / "examples/v0.2"
    folder.mkdir(parents=True, exist_ok=True)
    task = json.loads((ROOT / "examples/TaskSpec.json").read_text(encoding="utf-8"))
    project = {"schema_version": "opc.project.v0.2", "project_id": "example-compiler",
        "display_name": "GEMV compiler integration draft", "protocol_version": "opc.v0.2", "control_root": ".opc",
        "components": ["gemv"], "adapter_id": "unconfigured", "artifact_store_alias": "artifacts",
        "workspace_store_alias": "workspaces", "baseline_policy": "clean_commit_or_explicit_snapshot", "execution_enabled": False}
    component = {"schema_version": "opc.component.v0.2", "component_id": "gemv", "description": "接入结构示例，实际路径和命令尚未盘点",
        "adapter_id": "unconfigured", "source_roots": [], "editable_paths": [], "frozen_paths": [], "commands": [], "input_refs": [], "readiness": "draft"}
    artifact = {"uri": "artifact://example-compiler/gemv-row-block-proposal/template-run/attempts/a000001/submissions/template-submission/evidence.json",
        "sha256": "0"*64, "size_bytes": 0, "media_type": "application/json", "producer_job_id": "template-job"}
    task.update(schema_version="opc.taskspec.v0.2", project_id=project["project_id"], component_id="gemv",
        baseline={"kind": "source_snapshot", "source_ref": {"uri": "template://unresolved-source", "sha256": "0"*64, "locator": "DRAFT"},
            "git_commit": None, "includes_dirty_changes": False, "snapshot_manifest": artifact},
        requirements=[{"requirement_id": "req-gemv-001", "statement": "生成调度应正确执行且可由独立执行器复核",
            "current_state": "项目资产尚未盘点", "target_state": "候选代码、执行入口与独立复核均有固定证据",
            "negative_constraints": ["不改变evaluator与累加器约束"], "category": "functional", "priority": "must",
            "source_refs": task["source_requirements"], "success_criterion": "冻结工作负载逐项正确且真实入口执行通过", "verification_mode": "automated"}],
        context={"locked": ["数值语义与资源上限"], "delegated": ["合法tile候选与实现细节"],
            "deferred": ["真实PPA"], "canonical_refs": task["source_requirements"]},
        must_haves={"observables": [{"check_id": "check-exact-output", "requirement_ids": ["req-gemv-001"],
            "observation": "候选输出与独立参考一致", "verification": "冻结输入集的独立复算原件"}],
            "artifacts": [{"artifact_id": "kernel", "requirement_ids": ["req-gemv-001"], "logical_path": "candidate/source/kernel.py", "purpose": "待执行候选"},
                {"artifact_id": "runner", "requirement_ids": ["req-gemv-001"], "logical_path": "candidate/source/run.py", "purpose": "执行候选的入口"}],
            "key_links": [{"link_id": "link-runner-kernel", "requirement_ids": ["req-gemv-001"], "producer_artifact_id": "kernel",
                "consumer_artifact_id": "runner", "verification": "通过runner实际调用kernel并核对输出和调用证据"}]}, dependencies=[])
    task = TaskSpecV02.model_validate(task).model_dump(mode="json")
    binding = {"project_id": project["project_id"], "task_id": task["task_id"], "task_revision": 1,
        "task_spec_sha256": digest(task), "run_id": "template-run"}
    plan = dict(binding, schema_version="opc.plan.v0.2", plan_id="template-plan", attempt_id="a000001",
        requirement_ids=["req-gemv-001"], parent_submission_id=None, evidence_refs=[], hypothesis="输入复用减少搬运且保持功能",
        competing_explanation="少算或入口没有执行候选", change="调整tile", controlled_variables=["输入、模型、资源约束"],
        falsification="独立输出、资源门或真实调用链失败", files_modified=["kernel.py"], files_deleted=[], expected_artifact_ids=["kernel", "runner"],
        measurement_commands=[["registered-gemv-adapter", "evaluate"]], predicted_model_usd_upper_bound=0.0, predicted_wall_seconds=10)
    coverage = [{"requirement_id": "req-gemv-001", "status": "unverified", "check": "模板未执行",
        "verified_check_ids": [], "evidence": [], "human_judgment": False, "limitation": "原件占位，不能接纳"}]
    submission = dict(binding, schema_version="opc.submission.v0.2", submission_id="template-submission", attempt_id="a000001",
        plan_id="template-plan", producer_call_id="template-author", manifest_sha256="0"*64, artifacts=[artifact], claims=[],
        artifact_bindings=[{"artifact_id": item, "status": "missing", "artifact_ref": None, "reason": "模板未执行"} for item in ("kernel", "runner")],
        limitations=["结构示例"], failed_checks=[], environment_ref=artifact, coverage=coverage, deviations=[], provides=[], affects=[])
    axis = {"verdict": "inconclusive", "findings": ["没有真实运行证据"], "checked_artifacts": [artifact]}
    review = dict(binding, schema_version="opc.review.v0.2", review_id="template-review", review_call_id="template-reviewer",
        submission_id="template-submission", manifest_sha256="0"*64, standards=axis, spec=axis, recommended_disposition="blocked",
        conclusion="未验证", accepted_claims=[], coverage=coverage, unknowns=["执行与身份未验证"], gaps=["缺少执行原件"], checked_manifest_sha256="0"*64)
    for cls, value in zip(MODELS, [project, component, task, plan, submission, review], strict=True):
        cls.model_validate(value)
        (folder / f"{cls.__name__}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    export(ROOT / "schemas/v0.2")


if __name__ == "__main__":
    main()
