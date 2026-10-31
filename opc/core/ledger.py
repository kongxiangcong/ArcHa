"""The single authority for runs, attempts, champions, charges and control.

Git refs, STATE.md and report.json are projections of this database. openTPU kept
the champion as a branch *and* a champion.json written by its orchestrator,
which is two authorities; here the ref is written only after the ledger records
the intent, and reconciled on resume.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .model import Cost, Measurements, OPCError
from .platform import lock_writer, unlock_writer

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, revision TEXT NOT NULL,
  task_digest TEXT NOT NULL, component TEXT NOT NULL, base_commit TEXT NOT NULL,
  evaluator_digest TEXT NOT NULL, toolchain_digest TEXT NOT NULL, champion_ref TEXT NOT NULL,
  direction TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, stop_reason TEXT,
  created_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, at TEXT NOT NULL,
  kind TEXT NOT NULL, attempt_no INTEGER, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
  run_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, state TEXT NOT NULL,
  champion_before TEXT NOT NULL, focus TEXT, plan TEXT, patch_sha TEXT, files TEXT,
  gates TEXT, metrics TEXT, outcome TEXT, reason TEXT, gain REAL, cost TEXT,
  started_at TEXT NOT NULL, finished_at TEXT, PRIMARY KEY (run_id, attempt_no));
CREATE TABLE IF NOT EXISTS champions (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, commit_sha TEXT NOT NULL, metrics TEXT NOT NULL,
  attempt_no INTEGER, reason TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (run_id, seq));
CREATE TABLE IF NOT EXISTS charges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, attempt_no INTEGER,
  role TEXT NOT NULL, wall_seconds REAL NOT NULL, tokens INTEGER NOT NULL, usd REAL,
  usd_known INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS control (
  run_id TEXT PRIMARY KEY, command TEXT NOT NULL, at TEXT NOT NULL);
"""

FINAL_ATTEMPT_STATES = ("decided",)


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self._lock_fd: int | None = None

    # ------------------------------------------------------------- writer lock
    @contextmanager
    def writer(self) -> Iterator[None]:
        """One controller per project. A second `opc run` fails instead of racing
        the first for "the next attempt"."""
        lock = self.path.with_suffix(".lock")
        fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            lock_writer(fd)
        except BlockingIOError:
            os.close(fd)
            raise OPCError("another controller holds %s" % lock) from None
        except BaseException:
            os.close(fd)
            raise
        self._lock_fd = fd
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            owner = str(os.getpid()).encode()
            os.write(fd, owner)
            os.ftruncate(fd, len(owner))
            yield
        finally:
            try:
                unlock_writer(fd)
            finally:
                os.close(fd)
                self._lock_fd = None

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    # -------------------------------------------------------------------- runs
    def create_run(self, *, task_id: str, revision: str, task_digest: str, component: str,
                   base_commit: str, evaluator_digest: str, toolchain_digest: str,
                   champion_ref: str, direction: str) -> str:
        run_id = "run-" + uuid.uuid4().hex[:12]
        with self.tx() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (run_id, task_id, revision, task_digest, component, base_commit,
                        evaluator_digest, toolchain_digest, champion_ref, direction, "active",
                        None, now(), None))
            self._event(db, run_id, "run_created", None,
                        {"task": task_id, "revision": revision, "base": base_commit,
                         "evaluator_digest": evaluator_digest,
                         "toolchain_digest": toolchain_digest})
        return run_id

    def run(self, run_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise OPCError("unknown run %s" % run_id)
        return row

    def preparation_scope(self, task_id: str, create: bool = True) -> str | None:
        """Preparation owns ledger events/charges, never an execution Run.

        Reuse an existing legacy preparation row without rewriting its history.
        """
        legacy = self.db.execute("SELECT run_id FROM runs WHERE task_id=? AND revision='preparation' "
                                 "ORDER BY rowid DESC LIMIT 1", (task_id,)).fetchone()
        if legacy:
            return legacy["run_id"]
        scope = "preparation:" + task_id
        return scope if create or self.events(scope) else None

    def latest_run(self, task_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM runs WHERE task_id=? AND revision != 'preparation' ORDER BY created_at DESC, "
                               "rowid DESC LIMIT 1", (task_id,)).fetchone()

    def select_run(self, task_id: str, revision: str | None = None,
                   run_id: str | None = None) -> sqlite3.Row | None:
        """Resolve an execution identity; recency never breaks an ambiguity."""
        if run_id is not None:
            row = self.run(run_id)
            if row["task_id"] != task_id or row["revision"] == "preparation" or (
                    revision is not None and row["revision"] != revision):
                raise OPCError("run %s does not match selected Task/revision" % run_id)
            return row
        rows = [r for r in self.runs() if r["task_id"] == task_id and r["revision"] != "preparation"
                and (revision is None or r["revision"] == revision)]
        resumable = [r for r in rows if r["state"] != "closed"]
        candidates = resumable or rows
        if len(candidates) > 1:
            raise OPCError("multiple Runs require an explicit --run-id: " +
                           ", ".join(r["run_id"] for r in candidates))
        return candidates[0] if candidates else None

    def runs(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM runs ORDER BY created_at, rowid").fetchall()

    def set_run_state(self, run_id: str, state: str, stop_reason: str | None = None) -> None:
        with self.tx() as db:
            db.execute("UPDATE runs SET state=?, stop_reason=?, closed_at=? WHERE run_id=?",
                       (state, stop_reason, now() if state == "closed" else None, run_id))
            self._event(db, run_id, "run_" + state, None, {"stop_reason": stop_reason})

    def update_toolchain(self, run_id: str, digest: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE runs SET toolchain_digest=? WHERE run_id=?", (digest, run_id))
            self._event(db, run_id, "toolchain_changed", None, {"toolchain_digest": digest})

    # ------------------------------------------------------------------ events
    def _event(self, db: sqlite3.Connection, run_id: str, kind: str, attempt: int | None,
               body: dict[str, Any]) -> None:
        db.execute("INSERT INTO events (run_id, at, kind, attempt_no, body) VALUES (?,?,?,?,?)",
                   (run_id, now(), kind, attempt, json.dumps(body, default=str,
                                                             ensure_ascii=False)))

    def event(self, run_id: str, kind: str, attempt: int | None = None, **body: Any) -> None:
        with self.tx() as db:
            self._event(db, run_id, kind, attempt, body)

    def events(self, run_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM events WHERE run_id=?" + (" AND kind=?" if kind else "") + \
            " ORDER BY seq"
        rows = self.db.execute(q, (run_id, kind) if kind else (run_id,)).fetchall()
        return [{"seq": r["seq"], "at": r["at"], "kind": r["kind"], "attempt": r["attempt_no"],
                 "body": json.loads(r["body"])} for r in rows]

    def unresolved_accounting(self, run_id: str) -> list[dict[str, Any]]:
        resolved = {e["body"]["event_seq"] for e in self.events(run_id, "accounting_reconciled")}
        return [e for e in self.events(run_id, "accounting_unknown") if e["seq"] not in resolved]

    def reconcile_accounting(self, run_id: str, entries: list[dict[str, Any]], root: Path) -> None:
        """Apply evidence-backed missing charges atomically; preserve original events.

        Caller holds writer(). Amounts are *additional* usage, excluding receipts
        already charged and host usage. Replaying the identical entry is a no-op.
        """
        import hashlib
        import math
        if self._lock_fd is None:
            raise OPCError("accounting reconciliation requires the project writer lock")
        if not run_id.startswith("preparation:") and self.run(run_id)["revision"] != "preparation":
            raise OPCError("accounting reconciliation requires a preparation run")
        unknown = {e["seq"] for e in self.events(run_id, "accounting_unknown")}
        resolved = {e["body"]["event_seq"]: e["body"]
                    for e in self.events(run_id, "accounting_reconciled")}
        if not isinstance(entries, list) or not entries:
            raise OPCError("reconciliation requires nonempty entries")
        pending, seen = [], set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise OPCError("reconciliation entry must be an object")
            seq = entry.get("event_seq")
            tokens, wall = entry.get("additional_tokens"), entry.get("additional_wall_seconds")
            if type(seq) is not int or seq not in unknown or seq in seen:
                raise OPCError("reconciliation event_seq must name a unique unknown event in this preparation")
            seen.add(seq)
            if (type(tokens) is not int or tokens < 0 or type(wall) not in (int, float)
                    or not math.isfinite(wall) or wall < 0):
                raise OPCError("reconciliation usage must be finite and nonnegative; tokens must be an integer")
            if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                raise OPCError("reconciliation requires an accounting explanation")
            rel = entry.get("evidence")
            if not isinstance(rel, str) or not rel:
                raise OPCError("reconciliation requires an evidence file")
            evidence = (root / rel).resolve()
            if not evidence.is_relative_to(root.resolve()) or not evidence.is_file():
                raise OPCError("reconciliation evidence must be a readable project file")
            try:
                evidence_sha256 = hashlib.sha256(evidence.read_bytes()).hexdigest()
            except OSError as exc:
                raise OPCError("cannot read reconciliation evidence: " + str(exc)) from exc
            body = dict(event_seq=seq, additional_tokens=tokens, additional_wall_seconds=wall,
                        reason=entry["reason"], evidence=evidence.relative_to(root.resolve()).as_posix(),
                        evidence_sha256=evidence_sha256)
            if seq in resolved:
                if body != resolved[seq]:
                    raise OPCError("accounting event already reconciled with a different receipt")
                continue
            pending.append(body)
        with self.tx() as db:
            for body in pending:
                db.execute("INSERT INTO charges (run_id, role, wall_seconds, tokens, usd, usd_known, at) "
                           "VALUES (?,?,?,?,NULL,0,?)", (run_id, "accounting reconciliation",
                           body["additional_wall_seconds"], body["additional_tokens"], now()))
                self._event(db, run_id, "accounting_reconciled", None, body)

    # ---------------------------------------------------------------- attempts
    def next_attempt_no(self, run_id: str) -> int:
        row = self.db.execute("SELECT MAX(attempt_no) FROM attempts WHERE run_id=?",
                              (run_id,)).fetchone()
        return (row[0] or 0) + 1

    def begin_attempt(self, run_id: str, champion: str, focus: str | None) -> int:
        with self.tx() as db:
            row = db.execute("SELECT MAX(attempt_no) FROM attempts WHERE run_id=?",
                             (run_id,)).fetchone()
            n = (row[0] or 0) + 1
            db.execute("INSERT INTO attempts (run_id, attempt_no, state, champion_before, focus, "
                       "started_at) VALUES (?,?,?,?,?,?)",
                       (run_id, n, "started", champion, focus, now()))
            self._event(db, run_id, "attempt_started", n, {"champion": champion, "focus": focus})
        return n

    def update_attempt(self, run_id: str, n: int, state: str, **fields: Any) -> None:
        cols = {"state": state}
        for k, v in fields.items():
            cols[k] = json.dumps(v, default=str, ensure_ascii=False) \
                if k in ("plan", "files", "gates", "metrics", "cost") else v
        sets = ", ".join("%s=?" % k for k in cols)
        with self.tx() as db:
            db.execute("UPDATE attempts SET %s WHERE run_id=? AND attempt_no=?" % sets,
                       (*cols.values(), run_id, n))
            self._event(db, run_id, "attempt_" + state, n,
                        {k: v for k, v in fields.items() if k not in ("plan", "gates")})

    def finish_attempt(self, run_id: str, n: int, outcome: str, reason: str, gain: float,
                       cost: Cost, **fields: Any) -> None:
        self.update_attempt(run_id, n, "decided", outcome=outcome, reason=reason, gain=gain,
                            cost=cost.as_dict(), finished_at=now(), **fields)

    def attempts(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM attempts WHERE run_id=? ORDER BY attempt_no",
                               (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("plan", "files", "gates", "metrics", "cost"):
                d[k] = json.loads(d[k]) if d[k] else None
            out.append(d)
        return out

    def open_attempts(self, run_id: str) -> list[dict[str, Any]]:
        return [a for a in self.attempts(run_id) if a["state"] not in FINAL_ATTEMPT_STATES]

    # --------------------------------------------------------------- champions
    def record_champion_intent(self, run_id: str, n: int | None, old: str, new: str) -> None:
        self.event(run_id, "champion_intent", n, old=old, new=new)

    def set_champion(self, run_id: str, commit: str, metrics: Measurements, attempt: int | None,
                     reason: str) -> None:
        with self.tx() as db:
            row = db.execute("SELECT MAX(seq) FROM champions WHERE run_id=?",
                             (run_id,)).fetchone()
            seq = (row[0] or 0) + 1
            db.execute("INSERT INTO champions VALUES (?,?,?,?,?,?,?)",
                       (run_id, seq, commit, json.dumps(metrics.as_dict()), attempt, reason,
                        now()))
            self._event(db, run_id, "champion_set", attempt,
                        {"commit": commit, "seq": seq, "reason": reason,
                         "values": metrics.values})

    def champion(self, run_id: str) -> tuple[str, Measurements] | None:
        row = self.db.execute("SELECT * FROM champions WHERE run_id=? ORDER BY seq DESC LIMIT 1",
                              (run_id,)).fetchone()
        if row is None:
            return None
        return row["commit_sha"], Measurements.from_dict(json.loads(row["metrics"]))

    def champions(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM champions WHERE run_id=? ORDER BY seq",
                               (run_id,)).fetchall()
        return [{**dict(r), "metrics": json.loads(r["metrics"])} for r in rows]

    # ----------------------------------------------------------------- charges
    def charge(self, run_id: str, attempt: int | None, role: str, cost: Cost) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO charges (run_id, attempt_no, role, wall_seconds, tokens, usd, "
                       "usd_known, at) VALUES (?,?,?,?,?,?,?,?)",
                       (run_id, attempt, role, cost.wall_seconds, cost.tokens, cost.usd,
                        0 if cost.usd is None else 1, now()))

    def totals(self, run_id: str) -> dict[str, Any]:
        r = self.db.execute("SELECT COALESCE(SUM(wall_seconds),0), COALESCE(SUM(tokens),0), "
                            "COALESCE(SUM(usd),0), COALESCE(MIN(usd_known),1) FROM charges "
                            "WHERE run_id=?", (run_id,)).fetchone()
        return {"wall_seconds": r[0], "tokens": r[1], "usd": r[2], "usd_known": bool(r[3])}

    def task_totals(self, task_id: str) -> dict[str, Any]:
        records = [self.totals(r["run_id"]) for r in self.runs() if r["task_id"] == task_id]
        records.append(self.totals("preparation:" + task_id))
        return {"wall_seconds": sum(r["wall_seconds"] for r in records),
                "tokens": sum(r["tokens"] for r in records),
                "usd": sum(r["usd"] for r in records),
                "usd_known": all(r["usd_known"] for r in records)}

    # ----------------------------------------------------------------- control
    def set_control(self, run_id: str, command: str) -> None:
        if command not in ("run", "pause", "stop"):
            raise OPCError("unknown control command %r" % command)
        with self.tx() as db:
            db.execute("INSERT INTO control VALUES (?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                       "command=excluded.command, at=excluded.at", (run_id, command, now()))
            self._event(db, run_id, "control_" + command, None, {})

    def control(self, run_id: str) -> str:
        row = self.db.execute("SELECT command FROM control WHERE run_id=?", (run_id,)).fetchone()
        return row["command"] if row else "run"

    def close(self) -> None:
        self.db.close()
