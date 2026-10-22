"""Git operations: isolated trees, the sandbox, candidate patches and the champion ref.

The evaluated object is a patch restricted to editable paths, applied to a fresh
tree cut from the champion *commit*. Consequences, each learned on openTPU:

  * a candidate cannot influence evaluation through ignored caches, symlinked
    build dirs or leftover files, because none of them survive into the clean tree;
  * a slot is cut from a commit, never a branch (a branch moved mid-round and
    the next patch no longer applied);
  * the evaluator in the clean tree is the champion's, which equals the frozen
    baseline's because no accepted patch may touch evaluator files.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import ComponentConfig, matches
from .model import OPCError

ZERO = "0" * 40
GIT_ID = ["-c", "user.name=opc", "-c", "user.email=opc@localhost", "-c", "commit.gpgsign=false"]


def git(*args: str, cwd: Path, check: bool = True, input: str | bytes | None = None,
        binary: bool = False) -> str | bytes:
    """Raw stdout. Never strip it: porcelain lines start with a status column and
    stripping the first line shifted every path by one character on openTPU."""
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, input=input,
                       text=not binary)
    if check and r.returncode != 0:
        err = r.stderr if isinstance(r.stderr, str) else r.stderr.decode(errors="replace")
        raise OPCError("git %s failed in %s: %s" % (" ".join(args[:3]), cwd, err.strip()[-500:]))
    return r.stdout


def rev_parse(repo: Path, ref: str) -> str:
    return str(git("rev-parse", "--verify", ref + "^{commit}", cwd=repo)).strip()


def read_ref(repo: Path, ref: str) -> str | None:
    r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=str(repo),
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def cas_update_ref(repo: Path, ref: str, new: str, old: str | None) -> None:
    """Compare-and-swap: fails if someone else moved the ref since we read it."""
    git("update-ref", "-m", "opc champion", ref, new, old or ZERO, cwd=repo)


def tracked_digest(repo: Path, commit: str, patterns: list[str],
                   exclude: list[str] | None = None) -> tuple[str, list[str]]:
    """Digest of the tracked files matching `patterns` at `commit` (path + blob id).
    `exclude` drops scratch files (caches someone committed) from the evaluator."""
    out = str(git("ls-tree", "-r", "-z", "--full-tree", commit, cwd=repo))
    entries = []
    for item in out.split("\0"):
        if not item:
            continue
        meta, path = item.split("\t", 1)
        if matches(path, patterns) and not (exclude and matches(path, exclude)):
            entries.append((path, meta.split()[2]))
    entries.sort()
    h = hashlib.sha256()
    for path, blob in entries:
        h.update(("%s\0%s\n" % (path, blob)).encode())
    return h.hexdigest(), [p for p, _ in entries]


def dirty_paths(repo: Path) -> list[str]:
    out = str(git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=repo))
    paths, items, i = [], out.split("\0"), 0
    while i < len(items):
        item = items[i]
        if not item:
            i += 1
            continue
        status, path = item[:2], item[3:]
        paths.append(path)
        if status[0] in "RC":
            i += 1            # -z puts the rename source in the next field
        i += 1
    return paths


@dataclass
class SandboxReport:
    editable: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    scratch: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def as_dict(self) -> dict:
        return {"editable": self.editable, "violations": self.violations,
                "scratch": self.scratch[:50], "ignored": self.ignored[:50]}


class Workspaces:
    """Trees for one run under `<workspace_root>/<project>/<task>/<run>/`."""

    def __init__(self, repo: Path, root: Path):
        self.repo = repo
        self.root = root

    def checkout(self, name: str, commit: str) -> Path:
        wt = self.root / name
        if wt.exists():
            self.drop(wt)
        wt.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "--detach", "--force", str(wt), commit, cwd=self.repo)
        return wt

    def drop(self, wt: Path) -> None:
        git("worktree", "remove", "--force", str(wt), cwd=self.repo, check=False)
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
        git("worktree", "prune", cwd=self.repo, check=False)

    def drop_all(self) -> None:
        if self.root.exists():
            for p in sorted(self.root.rglob(".git"), reverse=True):
                self.drop(p.parent)
            shutil.rmtree(self.root, ignore_errors=True)


def stage_all(wt: Path) -> None:
    git("add", "-A", cwd=wt)


def sandbox(comp: ComponentConfig, wt: Path, base: str) -> SandboxReport:
    """Classify every change the worker left relative to `base`.

    Committed, staged, modified and untracked changes all count (a worker that
    runs `git commit` cannot hide its edits). Ignored files are reported but
    cannot reach evaluation, which runs on a clean tree.
    """
    stage_all(wt)
    names = str(git("diff", "--cached", "--name-only", "-z", "--no-renames", base, cwd=wt))
    rep = SandboxReport()
    for path in sorted(p for p in names.split("\0") if p):
        if comp.is_editable(path):
            rep.editable.append(path)
        elif comp.is_scratch(path):
            rep.scratch.append(path)
        else:
            rep.violations.append(path)
    ignored = str(git("status", "--porcelain=v1", "-z", "--ignored=matching",
                      "--untracked-files=all", cwd=wt))
    for item in ignored.split("\0"):
        if item.startswith("!! "):
            rep.ignored.append(item[3:])
    return rep


def extract_patch(wt: Path, base: str, paths: list[str]) -> str:
    if not paths:
        return ""
    return str(git("diff", "--cached", "--binary", "--no-renames", base, "--", *paths, cwd=wt))


def apply_patch(wt: Path, patch: str) -> None:
    if patch.strip():
        git("apply", "--index", "--binary", "--whitespace=nowarn", "-", cwd=wt, input=patch)


def commit_tree(wt: Path, message: str) -> str:
    git(*GIT_ID, "commit", "-q", "--no-verify", "-m", message, cwd=wt)
    return str(git("rev-parse", "HEAD", cwd=wt)).strip()


def patch_digest(patch: str) -> str:
    return hashlib.sha256(patch.encode()).hexdigest()
