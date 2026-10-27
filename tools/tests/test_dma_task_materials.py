"""Verify the task's independent acceptance materials, not an ArcHa implementation."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import unittest
import tempfile

ROOT = Path(__file__).parent / "fixtures" / "dma_backpressure"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


a = load("dma_acceptance_material", ROOT / "acceptance.py")
baseline = load("dma_serial_material", ROOT / "starter" / "dma_model.py")


def control(case):
    baseline.validate(case)
    return a.oracle(case)


def _check_hand_calculated_depth_one():
    result = a.oracle(a.base(1))
    assert result == {"events": [
        {"id": "a", "admitted": 0, "start": 0, "end": 3},
        {"id": "b", "admitted": 3, "start": 3, "end": 6},
        {"id": "c", "admitted": 3, "start": 3, "end": 5}],
        "memory": [1, 2, 3, 4] * 3, "checksums": {"c": 10}, "total_cycles": 6}


def _check_hand_calculated_depth_two():
    result = a.oracle(a.base(2))
    assert result["events"] == [
        {"id": "a", "admitted": 0, "start": 0, "end": 3},
        {"id": "b", "admitted": 0, "start": 3, "end": 6},
        {"id": "c", "admitted": 0, "start": 0, "end": 2}]
    assert result["memory"] == [1, 2, 3, 4] * 3


ANCHORS = [
    ("compute_reads_at_start", 8, {"c": 0}),
    ("completion_before_issue", 6, {"c": 10}),
    ("dependency", 8, {"c": 10}),
    ("empty", 0, {}),
    ("ceil_bandwidth", 3, {}),
    ("compute_busy", 4, {"x": 10, "y": 10}),
]
def _check_independent_hand_anchors(name, total, checksums):
    row = next(r for r in a.corpus()["cases"] if r["name"] == name)
    result = a.oracle(row["input"])
    assert result["total_cycles"] == total
    assert result["checksums"] == checksums


def _check_overlapping_copy_snapshot():
    row = next(r for r in a.corpus()["cases"] if r["name"] == "overlapping_copy")
    assert a.oracle(row["input"])["memory"] == [1, 1, 2, 3, 4, 6]


def _check_determinism_and_validity():
    assert a.corpus() == a.corpus()
    rows = a.corpus()["cases"]
    assert len(rows) == 82 and sum(r["invalid"] for r in rows) == 8
    assert a.check_function(control, rows)["passed"]
    for row in rows:
        if row["invalid"]:
            continue
        case = row["input"]
        changed = copy.deepcopy(case)
        shift = 7
        for job in changed["descriptors"]:
            job["release"] = job.get("release", 0) + shift
        original, delayed = a.oracle(case), a.oracle(changed)
        assert original["memory"] == delayed["memory"]
        assert original["checksums"] == delayed["checksums"]
        for old, new in zip(original["events"], delayed["events"]):
            assert all(new[k] == old[k] + shift for k in ("admitted", "start", "end"))


FAULTS = ["unbounded", "off_by_one", "wrong_memory", "wrong_checksum", "mutates_input", "accepts_invalid"]
def _check_rejects_deliberate_faults(bug):
    def mutant(case):
        if bug == "accepts_invalid":
            try:
                baseline.validate(case)
            except ValueError:
                return {}
        data = copy.deepcopy(case)
        if bug == "unbounded":
            baseline.validate(data)
            data["config"]["queue_depth"] = 1000
        result = control(data)
        if bug == "off_by_one":
            result["total_cycles"] += 1
        elif bug == "wrong_memory" and result["memory"]:
            result["memory"][0] ^= 1
        elif bug == "wrong_checksum" and result["checksums"]:
            key = next(iter(result["checksums"]))
            result["checksums"][key] += 1
        elif bug == "mutates_input":
            case["memory"].append(0)
        return result
    assert not a.check_function(mutant, a.corpus()["cases"])["passed"]


def _check_serial_baseline_rejected_but_valid():
    report = a.check_function(baseline.simulate, a.corpus()["cases"])
    assert not report["passed"]
    names = {f["name"] for f in report["failures"]}
    assert {"depth_one", "depth_two", "compute_reads_at_start"} <= names
    assert not names & {r["name"] for r in a.corpus()["cases"] if r["invalid"]}


def _check_external_cli_positive_and_negative(tmp_path):
    data = tmp_path / "inputs.json"
    data.write_text(json.dumps(a.corpus()))
    # Positive control is generated ONLY in a temporary examiner directory.
    # It must never be distributed to the task workers as a candidate solution.
    good = tmp_path / "control.py"
    good.write_text(
        "import sys,json\n"
        f"sys.path[:0] = {repr([str(ROOT.resolve()), str((ROOT/'starter').resolve())])}\n"
        "from acceptance import oracle\nfrom dma_model import validate\n"
        "def simulate(case):\n validate(case)\n return oracle(case)\n"
        "if __name__ == '__main__':\n"
        " try:\n  print(json.dumps(simulate(json.load(open(sys.argv[1])))))\n"
        " except ValueError:\n  sys.exit(2)\n", encoding="utf-8")
    for candidate, code in ((good, 0), (ROOT / "starter/dma_model.py", 1)):
        proc = subprocess.run([sys.executable, str(ROOT / "acceptance.py"), "evaluate",
                               "--candidate", str(candidate), "--data", str(data)],
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode == code, proc.stdout + proc.stderr
        assert json.loads(proc.stdout)["passed"] is (code == 0)


class MaterialTests(unittest.TestCase):
    def test_depth_one(self):
        _check_hand_calculated_depth_one()

    def test_depth_two(self):
        _check_hand_calculated_depth_two()

    def test_hand_anchors(self):
        for name, total, checksums in ANCHORS:
            with self.subTest(name=name):
                _check_independent_hand_anchors(name, total, checksums)

    def test_copy_snapshot(self):
        _check_overlapping_copy_snapshot()

    def test_generated_cases_and_time_shift(self):
        _check_determinism_and_validity()

    def test_fault_detection(self):
        for bug in FAULTS:
            with self.subTest(bug=bug):
                _check_rejects_deliberate_faults(bug)

    def test_serial_baseline(self):
        _check_serial_baseline_rejected_but_valid()

    def test_external_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            _check_external_cli_positive_and_negative(Path(directory))


if __name__ == "__main__":
    unittest.main()
