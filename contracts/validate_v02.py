"""Validate linked v0.2 contracts; deliberate negative cases are not run receipts."""
import copy
import json
from pathlib import Path
from typing import Any

from models_v02 import (
    MODELS,
    ComponentConfig,
    ExperimentPlanV02,
    ProjectConfig,
    ReviewDecisionV02,
    SubmissionV02,
    TaskSpecV02,
    check_bundle,
)
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).parent


def load(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "examples/v0.2" / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    for cls in MODELS:
        cls.model_validate(load(cls.__name__))
        schema = json.loads((ROOT / "schemas/v0.2" / f"{cls.__name__}.schema.json").read_text(encoding="utf-8"))
        assert schema == cls.model_json_schema(), f"stale schema {cls.__name__}"
    task = TaskSpecV02.model_validate(load("TaskSpecV02"))
    plan = ExperimentPlanV02.model_validate(load("ExperimentPlanV02"))
    submission = SubmissionV02.model_validate(load("SubmissionV02"))
    review = ReviewDecisionV02.model_validate(load("ReviewDecisionV02"))
    assert not check_bundle(task, plan, submission, review)
    assert task.authorization_ref is None and task.open_decisions
    negative_cases: list[tuple[type[BaseModel], dict[str, Any]]] = []
    bad = load("TaskSpecV02")
    bad["requirements"].append(copy.deepcopy(bad["requirements"][0]))
    negative_cases.append((TaskSpecV02, bad))
    bad = load("TaskSpecV02")
    bad["must_haves"]["observables"][0]["requirement_ids"] = ["unknown"]
    negative_cases.append((TaskSpecV02, bad))
    bad = load("TaskSpecV02")
    bad["must_haves"]["key_links"][0]["consumer_artifact_id"] = "missing"
    negative_cases.append((TaskSpecV02, bad))
    bad = load("TaskSpecV02")
    bad["baseline"]["snapshot_manifest"] = None
    negative_cases.append((TaskSpecV02, bad))
    bad = load("ReviewDecisionV02")
    bad["coverage"][0]["status"] = "pass"
    negative_cases.append((ReviewDecisionV02, bad))
    bad = load("ReviewDecisionV02")
    bad["recommended_disposition"] = "accept"
    negative_cases.append((ReviewDecisionV02, bad))
    bad = load("ReviewDecisionV02")
    bad["checked_manifest_sha256"] = "1"*64
    negative_cases.append((ReviewDecisionV02, bad))
    bad = load("ProjectConfig")
    bad["project_id"] = "../other"
    negative_cases.append((ProjectConfig, bad))
    bad = load("ProjectConfig")
    bad["execution_enabled"] = True
    negative_cases.append((ProjectConfig, bad))
    bad = load("ComponentConfig")
    bad["editable_paths"] = ["../outside"]
    negative_cases.append((ComponentConfig, bad))
    for bad_cls, value in negative_cases:
        try:
            bad_cls.model_validate(value)
        except ValidationError:
            continue
        raise AssertionError(f"invalid {bad_cls.__name__} accepted")
    # Cross-object attacks remain structurally valid, so exercise bundle checks separately.
    stale = review.model_copy(update={"task_spec_sha256": "1"*64})
    assert check_bundle(task, plan, submission, stale)
    wrong_project = plan.model_copy(update={"project_id": "another-project"})
    assert check_bundle(task, wrong_project, submission, review)
    missing = review.model_copy(update={"coverage": []})
    assert check_bundle(task, plan, submission, missing)
    bad = load("ReviewDecisionV02")
    bad["coverage"][0].update(status="pass", verified_check_ids=["check-exact-output"], evidence=submission.artifacts[0:1])
    partial = ReviewDecisionV02.model_validate(bad)
    assert check_bundle(task, plan, submission, partial), "missing actual integration check must be detected"
    bad = load("ReviewDecisionV02")
    bad["coverage"][0].update(status="pass", verified_check_ids=["check-exact-output", "link-runner-kernel"], evidence=submission.artifacts[0:1])
    missing_artifacts = ReviewDecisionV02.model_validate(bad)
    assert "passed requirement lacks a concrete required artifact binding" in check_bundle(task, plan, submission, missing_artifacts)
    absent_binding = submission.model_copy(update={"artifact_bindings": []})
    assert check_bundle(task, plan, absent_binding, review)
    bad = load("SubmissionV02")
    bad["artifact_bindings"][0].update(status="present", reason=None, artifact_ref={**bad["artifacts"][0], "uri": "artifact://undeclared/object"})
    unknown_ref = SubmissionV02.model_validate(bad)
    assert check_bundle(task, plan, unknown_ref, review)
    print("v0.2: 6 examples + 6 schemas + linked bundle valid; 10 invalid payloads and 7 invalid bundles rejected; draft stays disabled")


if __name__ == "__main__":
    main()
