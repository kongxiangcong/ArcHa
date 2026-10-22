"""LangGraph routing, SQLite authority, deterministic offline providers."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

try:
    from .domain import CONTRACT, design, digest, write_json
except ImportError:
    from domain import CONTRACT, design, digest, write_json  # type: ignore[no-redef]

HERE = Path(__file__).resolve().parent
TERMINAL = {"complete", "paused", "blocked"}


class GraphState(TypedDict):
    run_dir: str
    phase: str


class Run:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.db = sqlite3.connect(self.root / "ledger.sqlite3")
        self.db.row_factory = sqlite3.Row

    def close(self) -> None:
        self.db.close()

    @classmethod
    def create(cls, root: Path, max_attempts: int = 8) -> Run:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise ValueError("run directory must be empty; use resume for an existing run")
        run = cls(root)
        run.db.executescript("""
        CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
        CREATE TABLE events (seq INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE jobs (key TEXT PRIMARY KEY, role TEXT NOT NULL, status TEXT NOT NULL,
                           invocation TEXT NOT NULL, pid INTEGER, result TEXT);
        """)
        write_json(run.root / "contract.json", CONTRACT)
        domain_bytes = (HERE / "domain.py").read_bytes()
        (run.root / "domain.py").write_bytes(domain_bytes)
        state = {"phase": "expert", "attempts": 0, "max_attempts": max_attempts,
                 "contract_hash": digest(CONTRACT), "history": [], "best": None,
                 "reason": None, "manifest_hash": None,
                 "domain_hash": hashlib.sha256(domain_bytes).hexdigest(),
                 "domain_snapshot": "domain.py",
                 "provider": "offline_deterministic", "model_cost": "not_applicable_no_model_calls"}
        with run.db:
            run.db.execute("INSERT INTO state VALUES (1, ?)", (json.dumps(state),))
            run.event("created", {"contract_hash": state["contract_hash"]})
        return run

    def state(self) -> dict[str, Any]:
        return json.loads(self.db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])

    def save(self, state: dict[str, Any], kind: str) -> None:
        with self.db:
            self.db.execute("UPDATE state SET body=? WHERE id=1", (json.dumps(state),))
            self.event(kind, state)

    def event(self, kind: str, value: Any) -> None:
        self.db.execute("INSERT INTO events(at,kind,body) VALUES(?,?,?)", (time.time(), kind, json.dumps(value)))

    def attempt_dir(self, state: dict[str, Any]) -> Path:
        return self.root / f"attempt-{state['attempts']:03d}"

    def intact(self, state: dict[str, Any]) -> bool:
        try:
            contract = json.loads((self.root / "contract.json").read_text())
            return (digest(contract) == state["contract_hash"] and
                    hashlib.sha256((HERE / "domain.py").read_bytes()).hexdigest() == state["domain_hash"] and
                    hashlib.sha256((self.root / "domain.py").read_bytes()).hexdigest() == state["domain_hash"])
        except (OSError, ValueError):
            return False

    def expert(self, state: dict[str, Any]) -> None:
        if state["attempts"] >= state["max_attempts"]:
            state.update(phase="complete", reason="budget_exhausted")
            return
        history = state["history"]
        tried = {r["tile"] for r in history}
        good = [r["tile"] for r in history if r["accepted"]]
        upper = [r["tile"] for r in history if "accumulator resource limit exceeded" in r["findings"]]
        best = max(good, default=1)
        if not history:
            tile, hypothesis = 1, "Establish the untiled functional and transfer baseline."
        elif upper:
            tile = (best + min(upper)) // 2
            hypothesis = "Resource failure bounds the search; bisect between verified and rejected tile."
        else:
            tile = best * 2
            hypothesis = "Reuse each loaded input across more output rows; test doubled row tile."
        if tile in tried:
            state.update(phase="complete", reason="search_boundary_reached")
            return
        # Attempt budget is charged before design/experiment, including failed attempts.
        state["attempts"] += 1
        directory = self.attempt_dir(state)
        directory.mkdir(exist_ok=True)
        state.update(tile=tile, phase="design", manifest_hash=None, review_retries=0)
        write_json(directory / "plan.json", {"tile": tile, "hypothesis": hypothesis,
                   "feedback": history[-1] if history else None, "contract_hash": state["contract_hash"],
                   "expected_observation": "Fewer input reads, same exact output, bounded accumulator use"})

    def design(self, state: dict[str, Any], broken_tail: bool = False) -> None:
        self.attempt_dir(state).joinpath("candidate.py").write_text(design(state["tile"], broken_tail), encoding="utf-8")
        state["phase"] = "experiment"

    def job_key(self, state: dict[str, Any], role: str) -> str:
        suffix = f":retry{state.get('review_retries', 0)}" if role == "reviewer" else ""
        return f"{state['attempts']}:{role}{suffix}"

    def child(self, state: dict[str, Any], role: str) -> dict[str, Any] | None:
        key = self.job_key(state, role)
        existing = self.db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
        if existing:
            if existing["status"] == "completed":
                return json.loads(existing["result"])
            state.update(phase="blocked", reason=f"unknown_inflight_job:{key}; reconcile before retry")
            return None
        invocation = str(uuid.uuid4())
        # Intent commits before process launch. A crash in this gap intentionally blocks recovery.
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)", (key, role, "intent", invocation, None, None))
            self.event("job_intent", {"key": key, "role": role, "invocation": invocation})
        command = [sys.executable, str(HERE / "domain.py"), str(self.attempt_dir(state) / "candidate.py"),
                   "--tile", str(state["tile"])]
        if role == "reviewer":
            command.append("--review")
        started = time.time()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with self.db:
            self.db.execute("UPDATE jobs SET status='running',pid=? WHERE key=?", (process.pid, key))
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            stderr += "\nchild timeout"
        receipt: dict[str, Any] = {"invocation": invocation, "role": role, "pid": process.pid,
                    "command": command, "started": started, "ended": time.time(),
                    "exit_code": process.returncode, "stdout": stdout, "stderr": stderr}
        try:
            receipt["result"] = json.loads(stdout) if process.returncode == 0 else None
        except json.JSONDecodeError:
            receipt["result"] = None
        filename = f"reviewer-{state.get('review_retries', 0)}.json" if role == "reviewer" else "experiment.json"
        write_json(self.attempt_dir(state) / filename, receipt)
        with self.db:
            self.db.execute("UPDATE jobs SET status='completed',result=? WHERE key=?", (json.dumps(receipt), key))
            self.event("job_receipt", {"key": key, "invocation": invocation, "exit_code": process.returncode})
        return receipt

    def experiment(self, state: dict[str, Any]) -> None:
        result = self.child(state, "experiment")
        if result is not None:
            state["phase"] = "freeze"

    def freeze(self, state: dict[str, Any]) -> None:
        directory = self.attempt_dir(state)
        manifest = {"contract_hash": state["contract_hash"], "domain_hash": state["domain_hash"],
                    "files": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                              for name in ("plan.json", "candidate.py", "experiment.json")}}
        state["manifest_hash"] = digest(manifest)
        write_json(directory / "manifest.json", manifest)
        state["phase"] = "review"

    def verify_manifest(self, state: dict[str, Any]) -> bool:
        directory = self.attempt_dir(state)
        try:
            manifest = json.loads((directory / "manifest.json").read_text())
            return (digest(manifest) == state["manifest_hash"] and self.intact(state) and
                    all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected
                        for name, expected in manifest["files"].items()))
        except (OSError, ValueError, KeyError):
            return False

    def review(self, state: dict[str, Any]) -> None:
        if not self.verify_manifest(state):
            state.update(phase="blocked", reason="submission_or_contract_changed")
            return
        result = self.child(state, "reviewer")
        if result is not None:
            if not result["result"]:
                state.update(phase="blocked", reason="reviewer_unavailable")
            else:
                state["phase"] = "decide"

    def decide(self, state: dict[str, Any]) -> None:
        if not self.verify_manifest(state):
            state.update(phase="blocked", reason="submission_or_contract_changed")
            return
        directory = self.attempt_dir(state)
        review = json.loads(self.db.execute("SELECT result FROM jobs WHERE key=?", (self.job_key(state, "reviewer"),)).fetchone()[0])
        result = review["result"]
        experiment = json.loads((directory / "experiment.json").read_text())
        successful_execution = experiment["result"] is not None
        agrees = successful_execution and experiment["result"].get("metrics") == result.get("metrics")
        accepted = (result["standards"]["verdict"] == "pass" and result["spec"]["verdict"] == "pass" and agrees)
        findings = result["spec"]["findings"] + result["standards"]["findings"]
        if not agrees:
            findings += ["experiment/review mismatch or execution failure"]
        record = {"attempt": state["attempts"], "tile": state["tile"], "accepted": accepted,
                  "manifest_hash": state["manifest_hash"], "contract_hash": state["contract_hash"],
                  "reviewer_invocation": review["invocation"], "metrics": result.get("metrics"),
                  "standards": result["standards"], "spec": result["spec"], "findings": findings}
        if accepted and (state["best"] is None or
                         record["metrics"]["scalar_transfers"] < state["best"]["metrics"]["scalar_transfers"]):
            state["best"] = record
            record["selection"] = "retained"
        else:
            record["selection"] = "rejected" if not accepted else "not_improved"
        write_json(directory / "decision.json", record)
        state["history"].append(record)
        state["phase"] = "expert"

    def step(self, phase: str) -> str:
        state = self.state()
        if state["phase"] != phase:
            raise ValueError("phase changed; concurrent controllers are unsupported")
        if not self.intact(state):
            state.update(phase="blocked", reason="contract_or_evaluator_changed")
        else:
            getattr(self, phase)(state)
        self.save(state, f"phase:{phase}")
        return str(state["phase"])

    def run(self, pause_after: int | None = None) -> dict[str, Any]:
        state = self.state()
        if state["phase"] == "paused":
            state.update(phase="expert", reason=None)
            self.save(state, "resumed")
        builder = StateGraph(GraphState)
        phases = ("expert", "design", "experiment", "freeze", "review", "decide")

        def route(value: GraphState) -> str:
            return END if value["phase"] in TERMINAL else value["phase"]

        def node(phase: str) -> Any:
            def execute(_: GraphState) -> GraphState:
                next_phase = self.step(phase)
                state = self.state()
                if (pause_after is not None and phase == "decide" and
                        state["attempts"] >= pause_after and next_phase == "expert"):
                    state.update(phase="paused", reason="safe_boundary_pause")
                    self.save(state, "paused")
                    next_phase = "paused"
                return {"run_dir": str(self.root), "phase": next_phase}
            return execute

        builder.add_conditional_edges(START, route)
        for phase in phases:
            builder.add_node(phase, node(phase))
            builder.add_conditional_edges(phase, route)
        graph = builder.compile()
        graph.invoke({"run_dir": str(self.root), "phase": self.state()["phase"]},
                     {"recursion_limit": 10 + 7 * self.state()["max_attempts"]})
        return self.report()

    def retry_review(self) -> dict[str, Any]:
        state = self.state()
        if state["phase"] != "blocked" or state["reason"] != "reviewer_unavailable":
            raise ValueError("only a settled reviewer infrastructure failure can be retried")
        if state.get("review_retries", 0) >= 2:
            raise ValueError("review retry budget exhausted")
        state.update(phase="review", reason=None, review_retries=state.get("review_retries", 0) + 1)
        self.save(state, "review_retry_requested")
        return self.run()

    def report(self) -> dict[str, Any]:
        state = self.state()
        events = [dict(row) for row in self.db.execute("SELECT * FROM events ORDER BY seq")]
        jobs = [dict(row) for row in self.db.execute("SELECT key,role,status,invocation,pid FROM jobs ORDER BY key")]
        invalid = []
        for record in state["history"]:
            snapshot = {**state, "attempts": record["attempt"], "manifest_hash": record["manifest_hash"]}
            if not self.verify_manifest(snapshot):
                invalid.append(record["attempt"])
        result = {**state, "jobs": jobs, "event_count": len(events),
                  "invalid_submissions": invalid,
                  "acceptance_currently_valid": state["best"] is not None and state["best"]["attempt"] not in invalid and self.intact(state),
                  "environment": {"python": sys.version, "langgraph": importlib.metadata.version("langgraph")},
                  "limitations": ["deterministic providers, no autonomous LLM research",
                                  "subprocess separation, not OS privilege isolation",
                                  "local scalar-transfer model, not cycle timing or hardware PPA",
                                  "single controller; unknown external work requires reconciliation"]}
        write_json(self.root / "report.json", result)
        write_json(self.root / "events.json", events)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "resume", "status", "retry-review"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--pause-after", type=int)
    args = parser.parse_args()
    run = Run.create(args.run_dir, args.max_attempts) if args.command == "run" else Run(args.run_dir)
    try:
        if args.command == "status":
            report = run.report()
        elif args.command == "retry-review":
            report = run.retry_review()
        else:
            report = run.run(args.pause_after)
        best = report["best"]
        print(json.dumps({"phase": report["phase"], "reason": report["reason"], "attempts": report["attempts"],
                          "best_tile": best["tile"] if best else None,
                          "acceptance_currently_valid": report["acceptance_currently_valid"],
                          "scalar_transfers": best["metrics"]["scalar_transfers"] if best else None}, indent=2))
    finally:
        run.close()


if __name__ == "__main__":
    main()
