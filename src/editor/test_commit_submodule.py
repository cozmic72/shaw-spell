#!/usr/bin/env python3
"""Focused tests for the editor daemon's Commit feature over the `data/` SUBMODULE.

The patch store lives inside the `data/` git submodule (patches/patches.jsonl), so a
commit runs git IN that submodule's working tree and stages ONLY the store pathspec,
then pushes to the submodule's remote. These tests exercise that path against a
THROWAWAY git repo standing in for the submodule (with a local bare repo as its
remote) via SHAW_SPELL_PATCH_STORE — the real data/ submodule and real store are
never touched.

Covers:
  - _commit_repo_root resolves the store's own repo toplevel (works with a submodule
    .git FILE too) and _commit_pathspec derives the store's repo-relative path
  - handle_commit_status reports the uncommitted count + HEAD sha/subject
  - handle_commit stages+commits ONLY the pathspec (a sibling dirty file is NOT swept
    in) and, with a working remote, pushes → pushed:true
  - a commit with no/broken remote still commits (durable locally) → pushed:false +
    push_error, WITHOUT failing the commit
  - _commit_repo_root returns None for a store that sits in no git checkout (→ commit
    unavailable)

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import editord


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args],
                   check=True, capture_output=True, text=True)


def _init_repo(root):
    """A committable git repo with identity + a stable branch name set locally."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "checkout", "-q", "-b", "main")


def _write_store(root, lines):
    store = root / "patches" / "patches.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    return store


def _patch_line(word):
    return json.dumps({"id": f"p_{word}", "op": "accept", "changes": {},
                       "anchor": {"word": word, "pos": "NN", "shaw": "x", "var": ""},
                       "meta": {"author": "joro", "origin": "editor"}})


class _store_at:
    """Point SHAW_SPELL_PATCH_STORE at `path` for the duration of the block, so the
    commit ops resolve their repo from that path — never the live store."""

    def __init__(self, path):
        self._path = path

    def __enter__(self):
        self._prev = os.environ.get("SHAW_SPELL_PATCH_STORE")
        os.environ["SHAW_SPELL_PATCH_STORE"] = str(self._path)
        return self._path

    def __exit__(self, *_exc):
        if self._prev is None:
            os.environ.pop("SHAW_SPELL_PATCH_STORE", None)
        else:
            os.environ["SHAW_SPELL_PATCH_STORE"] = self._prev
        return False


# ---- repo-root / pathspec resolution ----

def test_commit_repo_root_and_pathspec():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo(repo)
        store = _write_store(repo, [_patch_line("cat")])
        with _store_at(store):
            root = editord._commit_repo_root()
            assert root == repo.resolve(), root
            assert editord._commit_pathspec(root) == "patches/patches.jsonl", \
                editord._commit_pathspec(root)


def test_commit_repo_root_none_outside_checkout():
    """A store in a bare temp dir (no git) → committing unavailable."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "patches" / "patches.jsonl"
        store.parent.mkdir(parents=True)
        store.write_text(_patch_line("cat") + "\n", encoding="utf-8")
        with _store_at(store):
            assert editord._commit_repo_root() is None


def test_commit_repo_root_resolves_submodule_gitfile():
    """A submodule's `.git` is a FILE (gitdir: pointer), not a dir. Simulate that and
    assert rev-parse still resolves the toplevel, so `git -C` works on the real one."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        realgit = tmp / "modules" / "data"      # where a submodule's git dir lives
        work = tmp / "work"                     # the submodule working tree
        work.mkdir(parents=True)
        # Build a normal repo, then relocate its .git and leave a gitfile pointer.
        _init_repo(work)
        store = _write_store(work, [_patch_line("cat")])
        _git(work, "add", "--", "patches/patches.jsonl")
        _git(work, "commit", "-q", "-m", "seed")
        realgit.parent.mkdir(parents=True, exist_ok=True)
        (work / ".git").rename(realgit)
        (work / ".git").write_text(f"gitdir: {realgit}\n", encoding="utf-8")
        # core.worktree lets git resolve the working tree from the relocated gitdir.
        _git(work, "config", "core.worktree", str(work))
        with _store_at(store):
            root = editord._commit_repo_root()
            assert root == work.resolve(), root


# ---- commit_status ----

def test_commit_status_counts_and_head():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo(repo)
        store = _write_store(repo, [_patch_line("cat")])
        _git(repo, "add", "--", "patches/patches.jsonl")
        _git(repo, "commit", "-q", "-m", "seed 1 patch")
        # Add two more uncommitted patch lines.
        store.write_text(
            "".join(l + "\n" for l in
                    [_patch_line("cat"), _patch_line("dog"), _patch_line("fox")]),
            encoding="utf-8")
        with _store_at(store):
            status = editord.handle_commit_status(None, None)
        assert status["commit_available"] is True, status
        assert status["uncommitted"] == 2, status        # two ADDED lines
        assert status["subject"] == "seed 1 patch", status
        assert status["head"], status


def test_commit_status_unavailable_no_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "patches" / "patches.jsonl"
        store.parent.mkdir(parents=True)
        store.write_text(_patch_line("cat") + "\n", encoding="utf-8")
        with _store_at(store):
            assert editord.handle_commit_status(None, None) == \
                {"commit_available": False}


# ---- commit: stages only the pathspec, pushes ----

def test_commit_stages_only_pathspec_and_pushes():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bare = tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)],
                       check=True, capture_output=True, text=True)
        repo = tmp / "repo"
        repo.mkdir()
        _init_repo(repo)
        store = _write_store(repo, [_patch_line("cat")])
        # A DIRTY sibling file that must NOT be swept into the decision commit.
        other = repo / "regenerated.json"
        other.write_text("{}\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "seed store + sibling")
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "-u", "origin", "main")
        # Now make BOTH files dirty; only the store must be committed.
        store.write_text(
            "".join(l + "\n" for l in [_patch_line("cat"), _patch_line("dog")]),
            encoding="utf-8")
        other.write_text('{"regenerated": true}\n', encoding="utf-8")

        with _store_at(store):
            result = editord.handle_commit(None, None)

        assert result["result"] == "committed", result
        assert result["pushed"] is True, result
        assert "push_error" not in result, result
        # The commit touched ONLY the store, leaving the sibling still dirty.
        changed = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            check=True, capture_output=True, text=True).stdout.split()
        assert changed == ["patches/patches.jsonl"], changed
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            check=True, capture_output=True, text=True).stdout
        assert "regenerated.json" in dirty, dirty
        # The push landed on the bare remote (its HEAD == local HEAD).
        local_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        remote_head = subprocess.run(
            ["git", "-C", str(bare), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        assert local_head == remote_head, (local_head, remote_head)


def test_commit_succeeds_but_push_fails_no_remote():
    """No configured remote: the commit is durable locally, and the push failure is
    reported (pushed:false + push_error) WITHOUT failing the commit."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo(repo)
        store = _write_store(repo, [_patch_line("cat")])
        _git(repo, "add", "--", "patches/patches.jsonl")
        _git(repo, "commit", "-q", "-m", "seed")
        store.write_text(
            "".join(l + "\n" for l in [_patch_line("cat"), _patch_line("dog")]),
            encoding="utf-8")

        with _store_at(store):
            result = editord.handle_commit(None, None)

        assert result["result"] == "committed", result
        assert result["pushed"] is False, result
        assert result["push_error"], result
        # The commit is real even though the push failed.
        subject = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s"],
            check=True, capture_output=True, text=True).stdout.strip()
        assert subject.startswith("Editorial decisions"), subject


def test_commit_nothing_to_commit():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo(repo)
        _write_store(repo, [_patch_line("cat")])
        _git(repo, "add", "--", "patches/patches.jsonl")
        _git(repo, "commit", "-q", "-m", "seed")
        store = repo / "patches" / "patches.jsonl"
        with _store_at(store):
            assert editord.handle_commit(None, None) == \
                {"result": "nothing-to-commit"}


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
