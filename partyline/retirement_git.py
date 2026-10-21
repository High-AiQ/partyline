"""Bounded Git evidence and recoverable snapshots for explicit retirement."""

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile

from fastapi import HTTPException

from .git_fence import mirror_branch_ref
from .line_worktree import _git
from .worktree_lifecycle import _base_ref, _default_branch
from .worktree_paths import branch_name, managed_root

MAX_FILES = 2000
MAX_BYTES = 256 * 1024 * 1024
MAX_IGNORED_FILES = 100000
MAX_IGNORED_BYTES = 4 * 1024 * 1024 * 1024
HASH_BYTES = 1024 * 1024
MAX_HASH_BYTES = 16 * 1024 * 1024
DISPLAY = 100


def git(cwd, *args):
    try:
        done = _git(*args, cwd=cwd)
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise HTTPException(409, "cannot inspect retirement Git state") from exc
    if done.returncode:
        raise HTTPException(409, "cannot inspect retirement Git state")
    return done.stdout


def _paths(cwd, *args):
    return [p for p in git(cwd, *args).split('\0') if p]


def file_evidence(cwd, paths, *, ignored=False):
    """Hash small dirty files; large files use lstat identity and timestamps."""
    evidence, total, hashed = [], 0, 0
    file_limit = MAX_IGNORED_FILES if ignored else MAX_FILES
    byte_limit = MAX_IGNORED_BYTES if ignored else MAX_BYTES
    if len(paths) > file_limit:
        raise HTTPException(409, f"retirement exceeds {file_limit} file limit")
    for path in sorted(paths):
        full = os.path.join(cwd, path)
        try:
            info = os.lstat(full)
        except FileNotFoundError:
            evidence.append([path, "deleted"])
            continue
        total += info.st_size
        if total > byte_limit:
            raise HTTPException(409, f"retirement exceeds {byte_limit} byte limit")
        row = [path, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino]
        if stat.S_ISLNK(info.st_mode):
            row.append(os.readlink(full))
        elif stat.S_ISREG(info.st_mode):
            if not ignored and info.st_size <= HASH_BYTES and hashed + info.st_size <= MAX_HASH_BYTES:
                with open(full, 'rb') as stream:
                    row.append(hashlib.sha256(stream.read(HASH_BYTES + 1)).hexdigest())
                hashed += info.st_size
        else:
            raise HTTPException(409, "retirement contains unsupported file type")
        evidence.append(row)
    return evidence, total


def inspect_git(db, conv):
    cwd = conv.get("cwd") or ""
    root = managed_root(cwd)
    if not root or not os.path.isdir(cwd) or not os.path.lexists(os.path.join(cwd, ".git")):
        return None  # a task folder holding only worktrees has no repository of its own
    if os.path.realpath(cwd) != cwd or os.path.realpath(root) != root:
        raise HTTPException(409, "retirement requires canonical managed worktree paths")
    branch = branch_name(cwd)
    actual = git(cwd, "symbolic-ref", "-q", "HEAD").strip() if git(
        cwd, "rev-parse", "--abbrev-ref", "HEAD").strip() != "HEAD" else None
    if actual and actual != f"refs/heads/{branch}":
        raise HTTPException(409, "worktree is not on its assigned line branch")
    head = git(cwd, "rev-parse", "HEAD").strip()
    result = _git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=root)
    host_tip = result.stdout.strip() if result.returncode == 0 else None
    mirror_tip = mirror_branch_ref(cwd, conv["id"], branch)
    tips = list(dict.fromkeys(t for t in (head, host_tip, mirror_tip) if t))
    parent = db.get_conversation(conv.get("parent_id")) or {}
    bases = [b for b in (_base_ref(parent.get("cwd")), _default_branch(root)) if b]
    commits = git(cwd, "log", "--format=%H %s", "-101", *tips, "--not", *bases).splitlines()
    tracked = set(_paths(cwd, "diff", "--name-only", "-z", "HEAD"))
    tracked.update(_paths(cwd, "diff", "--cached", "--name-only", "-z"))
    untracked = _paths(cwd, "ls-files", "--others", "--exclude-standard", "-z")
    ignored = _paths(cwd, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    files, size = file_evidence(cwd, tracked | set(untracked))
    ignored_files, ignored_size = file_evidence(cwd, set(ignored), ignored=True)
    index_path = git(cwd, "rev-parse", "--path-format=absolute", "--git-path", "index").strip()
    index, _ = file_evidence(os.path.dirname(index_path), [os.path.basename(index_path)])
    return {"cwd": cwd, "root": root, "branch": branch, "head": head,
            "branch_tip": host_tip, "mirror_tip": mirror_tip,
            "unmerged_commits": commits[:DISPLAY], "commits_truncated": len(commits) > DISPLAY,
            "tracked": sorted(tracked), "untracked": untracked, "ignored": ignored,
            "files": files, "bytes": size, "index": index, "index_path": index_path,
            "ignored_files": ignored_files, "ignored_bytes": ignored_size}


def snapshot(state, audit_id):
    """Capture the real index and add -A state separately, using only private indexes."""
    cwd = state["cwd"]
    prefix = f"refs/partyline/discarded/{audit_id}"
    refs = {}
    with tempfile.TemporaryDirectory(prefix="partyline-discard-") as directory:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(directory, "index"),
               "GIT_AUTHOR_NAME": "Partyline", "GIT_AUTHOR_EMAIL": "partyline@local",
               "GIT_COMMITTER_NAME": "Partyline", "GIT_COMMITTER_EMAIL": "partyline@local"}

        def run(*args, input=None, failure="retirement recovery snapshot failed; worktree retained"):
            done = subprocess.run(["git", *args], cwd=cwd, env=env,
                                  input=input, capture_output=True, text=True, timeout=30)
            if done.returncode:
                raise HTTPException(409, failure)
            return done.stdout.strip()

        if os.path.isfile(state["index_path"]):
            shutil.copyfile(state["index_path"], env["GIT_INDEX_FILE"])
        else:
            run("read-tree", "--empty")
        if run("ls-files", "--unmerged", "-z"):
            raise HTTPException(409, "resolve or commit conflicted index before force retirement")
        index_tree = run("write-tree")
        index_sha = run("commit-tree", index_tree, "-p", state["head"],
                        "-m", f"Partyline index recovery {audit_id}")
        env["GIT_INDEX_FILE"] = os.path.join(directory, "working-index")
        run("read-tree", state["mirror_tip"] or state["head"])
        run("add", "-A", "--", ".")
        tree = run("write-tree")
        sha = run("commit-tree", tree, "-p", state["mirror_tip"] or state["head"],
                  "-m", f"Partyline retirement recovery {audit_id}")
        for name, tip in (("index", index_sha), ("snapshot", sha), ("head", state["head"]),
                          ("branch", state["branch_tip"]), ("mirror", state["mirror_tip"])):
            if tip:
                ref = f"{prefix}/{name}"
                refs[ref] = tip
        commands = "start\n" + "".join(f"create {ref} {tip}\n" for ref, tip in refs.items())
        run("update-ref", "--stdin", input=commands + "prepare\ncommit\n")
    return refs
