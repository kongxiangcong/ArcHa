"""Validate the checked-in interface examples and selected negative cases."""
import json
from pathlib import Path
from typing import Any

from models import (
    DecisionRequest,
    ExperimentPlan,
    JobRecord,
    ReviewDecision,
    Submission,
    TaskSpec,
)
from pydantic import BaseModel, ValidationError


def main() -> None:
    root = Path(__file__).parent
    classes = (TaskSpec, ExperimentPlan, Submission, ReviewDecision, DecisionRequest, JobRecord)
    for cls in classes:
        text = (root / "examples" / f"{cls.__name__}.json").read_text(encoding="utf-8")
        cls.model_validate_json(text)
        schema = json.loads((root / "schemas" / f"{cls.__name__}.schema.json").read_text(encoding="utf-8"))
        if schema != cls.model_json_schema():
            raise AssertionError(f"stale schema: {cls.__name__}")
    task_data = json.loads((root / "examples/TaskSpec.json").read_text(encoding="utf-8"))
    task = TaskSpec.model_validate(task_data)
    assert task.dispatch_problems(), "example must remain non-dispatchable without trusted authorization"
    negative_cases: list[tuple[type[BaseModel], dict[str, Any]]] = []
    bad = dict(task_data, unexpected_field=True)
    negative_cases.append((TaskSpec, bad))
    bad = json.loads(json.dumps(task_data))
    bad["budget"]["max_attempts"] = 0
    negative_cases.append((TaskSpec, bad))
    bad = json.loads(json.dumps(task_data))
    bad["acceptance"]["required_review_axes"] = ["spec", "spec"]
    negative_cases.append((TaskSpec, bad))
    bad = json.loads((root / "examples/ReviewDecision.json").read_text(encoding="utf-8"))
    bad["recommended_disposition"] = "accept"
    bad["standards"]["verdict"] = "fail"
    negative_cases.append((ReviewDecision, bad))
    for bad_cls, bad in negative_cases:
        try:
            bad_cls.model_validate(bad)
        except ValidationError:
            continue
        raise AssertionError(f"invalid {bad_cls.__name__} accepted")
    print("6 examples valid; 6 schemas synchronized; 4 negative cases rejected; draft dispatch blocked")


if __name__ == "__main__":
    main()
