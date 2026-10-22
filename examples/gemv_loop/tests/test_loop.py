from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from examples.gemv_loop import loop
from examples.gemv_loop.domain import design, execute
from examples.gemv_loop.loop import Run


def test_tail_bug_fails_independent_golden(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text(design(4, broken_tail=True))
    result = execute(candidate, 4, review=True)
    assert result["spec"]["verdict"] == "fail"
    assert "functional mismatch 5x7" in result["spec"]["findings"]


def test_actual_tile_13_cannot_be_reported_as_plan_tile_12(tmp_path: Path) -> None:
    # These tiles have identical transfer counts on all four workloads, so output
    # and metric agreement alone cannot prove compliance with the resource cap.
    candidate = tmp_path / "candidate.py"
    candidate.write_text(design(13))
    result = execute(candidate, 12, review=True)
    assert result["spec"]["verdict"] == "fail"
    assert "candidate TILE does not match frozen plan tile" in result["spec"]["findings"]


@pytest.mark.parametrize("declaration", ["TILE = True", "TILE = 6 + 6", "TILE = 12\nTILE = 12"])
def test_ambiguous_or_noninteger_tile_is_rejected(tmp_path: Path, declaration: str) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text(design(12).replace("TILE = 12", declaration, 1))
    result = execute(candidate, 12, review=True)
    assert result["spec"]["verdict"] == "fail"


def test_search_discovers_resource_boundary_and_counts_failures(tmp_path: Path) -> None:
    run = Run.create(tmp_path / "run", max_attempts=8)
    try:
        result = run.run()
        assert result["phase"] == "complete"
        assert result["attempts"] == 8
        assert result["reason"] == "budget_exhausted"
        assert result["best"]["tile"] == 12
        assert [row["tile"] for row in result["history"]] == [1, 2, 4, 8, 16, 12, 14, 13]
        rejected = [row for row in result["history"] if not row["accepted"]]
        assert {row["tile"] for row in rejected} == {16, 14, 13}
        assert len(result["jobs"]) == 16
        assert result["acceptance_currently_valid"]
    finally:
        run.close()


def test_pause_resume_in_new_process_does_not_repeat_completed_jobs(tmp_path: Path) -> None:
    root = tmp_path / "run"
    command = [sys.executable, str(loop.HERE / "loop.py")]
    subprocess.run(command + ["run", "--run-dir", str(root), "--max-attempts", "3", "--pause-after", "1"], check=True, capture_output=True)
    before = json.loads((root / "report.json").read_text())
    assert before["phase"] == "paused"
    subprocess.run(command + ["resume", "--run-dir", str(root)], check=True, capture_output=True)
    after = json.loads((root / "report.json").read_text())
    assert after["phase"] == "complete"
    assert len(after["jobs"]) == 6
    before_ids = {job["invocation"] for job in before["jobs"]}
    assert before_ids <= {job["invocation"] for job in after["jobs"]}


def test_unknown_external_job_blocks_without_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run.create(tmp_path / "run", max_attempts=2)
    try:
        run.step("expert")
        run.step("design")
        with run.db:
            run.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)", ("1:experiment", "experiment", "intent", "unknown", None, None))
        def forbidden(*args, **kwargs):
            raise AssertionError("must not launch unknown job twice")
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        result = run.run()
        assert result["phase"] == "blocked"
        assert "unknown_inflight_job" in result["reason"]
        assert result["best"] is None
    finally:
        run.close()


def test_changed_bytes_after_review_cannot_be_accepted(tmp_path: Path) -> None:
    run = Run.create(tmp_path / "run", 1)
    try:
        for phase in ("expert", "design", "experiment", "freeze", "review"):
            run.step(phase)
        candidate = run.root / "attempt-001" / "candidate.py"
        candidate.write_text(candidate.read_text() + "\n# changed\n")
        run.step("decide")
        assert run.state()["phase"] == "blocked"
        assert run.state()["best"] is None
    finally:
        run.close()


def test_status_invalidates_tampered_old_accepted_snapshot(tmp_path: Path) -> None:
    run = Run.create(tmp_path / "run", 1)
    try:
        assert run.run()["acceptance_currently_valid"]
        candidate = run.root / "attempt-001" / "candidate.py"
        candidate.write_text(candidate.read_text() + "\n# changed\n")
        report = run.report()
        assert not report["acceptance_currently_valid"]
        assert report["invalid_submissions"] == [1]
    finally:
        run.close()


def test_reviewer_failure_can_retry_only_reviewer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run.create(tmp_path / "run", 1)
    original = subprocess.Popen
    def fail_review(command, **kwargs):
        return original(command + (["--invalid-reviewer-option"] if "--review" in command else []), **kwargs)
    try:
        monkeypatch.setattr(subprocess, "Popen", fail_review)
        first = run.run()
        assert first["phase"] == "blocked"
        assert first["reason"] == "reviewer_unavailable"
        assert first["best"] is None
        experiment_id = next(j["invocation"] for j in first["jobs"] if j["role"] == "experiment")
        monkeypatch.setattr(subprocess, "Popen", original)
        final = run.retry_review()
        assert final["acceptance_currently_valid"]
        experiments = [j for j in final["jobs"] if j["role"] == "experiment"]
        assert [j["invocation"] for j in experiments] == [experiment_id]
        assert len(final["jobs"]) == 3
        assert final["attempts"] == 1
    finally:
        run.close()


def test_execution_failure_consumes_attempt_and_cannot_win(tmp_path: Path) -> None:
    run = Run.create(tmp_path / "run", 1)
    try:
        run.step("expert")
        run.step("design")
        (run.root / "attempt-001" / "candidate.py").write_text(design(1).replace("return out", "return []"))
        final = run.run()
        assert final["attempts"] == 1
        assert not final["history"][0]["accepted"]
        assert final["best"] is None
    finally:
        run.close()
