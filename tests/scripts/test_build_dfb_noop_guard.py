#!/usr/bin/env python3
"""Tests for the no-op commit guard in scripts/build_dfb_json.py.

When `out/dfb/<date>.json` already exists on disk and is byte-identical
to what's tracked in git, the build helper must NOT invoke
`git commit` or `git push`. It can still proceed to the Vercel
deploy step (or short-circuit if --skip-deploy).

These tests mock subprocess.run and assert the call sequence for the
three cases: file unchanged, file changed, and --dry-run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
BUILD = SCRIPTS / "build_dfb_json.py"

# Make scripts/ importable so we can import build_dfb_json directly.
sys.path.insert(0, str(SCRIPTS))

import build_dfb_json  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Stand up a fake git repo with one tracked DFB JSON.

    The fixture monkey-patches REPO_ROOT inside build_dfb_json to point
    at tmp_path, so write_and_ship operates on the fake repo.
    """
    fake = tmp_path / "fake-repo"
    fake.mkdir()
    out = fake / "out" / "dfb"
    out.mkdir(parents=True)

    # Initialize a real git repo so git ls-files / git status work.
    subprocess.run(["git", "init", "-q"], cwd=fake, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=fake, check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=fake, check=True)

    date_iso = "2026-07-01"
    json_path = out / f"{date_iso}.json"
    edition = {
        "date": date_iso,
        "weekday": "Wednesday",
        "kind": "dfb",
        "title": "Test",
        "sections": {"marketHeadlines": [{"headline": "x"}]},
    }
    json_path.write_text(json.dumps(edition), encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(json_path.relative_to(fake))],
                   cwd=fake, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=fake, check=True)

    # Point build_dfb_json at the fake repo.
    monkeypatch.setattr(build_dfb_json, "REPO_ROOT", fake)
    monkeypatch.setattr(build_dfb_json, "OUT_DIR", out)
    return {"root": fake, "out": out, "date": date_iso, "edition": edition}


def _subprocess_calls(mock_run):
    """Return the list of (argv,) tuples that subprocess.run was called with."""
    return [call.args[0] for call in mock_run.call_args_list]


def test_unchanged_file_skips_commit_and_push(fake_repo, monkeypatch):
    """When the on-disk JSON is byte-identical to what's tracked,
    write_and_ship must NOT invoke git add/commit/push."""
    # Don't modify the file — it's already tracked and unchanged.
    monkeypatch.setattr(build_dfb_json, "_vercel_deploy",
                        lambda *a, **kw: 0)

    with mock.patch("subprocess.run") as mock_run:
        # Make ls-files and status succeed (file is tracked, no changes).
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        rc = build_dfb_json.write_and_ship(
            fake_repo["edition"], fake_repo["date"],
            dry_run=False, skip_deploy=True,
        )

    assert rc == 0
    cmds = _subprocess_calls(mock_run)
    # git commit / git push must NOT appear in the call list.
    assert not any("commit" in c for c in cmds if isinstance(c, list))
    assert not any("push" in c for c in cmds if isinstance(c, list))


def test_dry_run_skips_everything(fake_repo):
    """--dry-run must skip commit, push, and Vercel deploy entirely."""
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        rc = build_dfb_json.write_and_ship(
            fake_repo["edition"], fake_repo["date"],
            dry_run=True, skip_deploy=False,
        )

    assert rc == 0
    cmds = _subprocess_calls(mock_run)
    # No git commit, no git push, no vercel.
    assert not any(
        isinstance(c, list) and "commit" in c for c in cmds
    )
    assert not any(
        isinstance(c, list) and "push" in c for c in cmds
    )
    assert not any(
        isinstance(c, list) and "vercel" in c for c in cmds
    )


def test_changed_file_does_commit_and_push(fake_repo, monkeypatch):
    """When the on-disk JSON differs from what's tracked, write_and_ship
    must call git add, commit, and push."""
    # Modify the edition dict so write_and_ship writes different bytes
    # to disk (line 187 runs before the no-op guard at line ~200).
    modified_edition = {**fake_repo["edition"], "title": "Modified for test"}

    monkeypatch.setattr(build_dfb_json, "_vercel_deploy",
                        lambda *a, **kw: 0)

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, list):
            if "ls-files" in cmd:
                # Tracked, no error.
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="", stderr="",
                )
            if "status" in cmd:
                # File has been modified on disk — porcelain output is
                # non-empty (single line starting with " M ").
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout=" M out/dfb/2026-07-01.json\n", stderr="",
                )
        # Default: pretend it succeeded.
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )

    add_called = commit_called = push_called = False
    def track_calls(cmd, *args, **kwargs):
        nonlocal add_called, commit_called, push_called
        if isinstance(cmd, list):
            if "add" in cmd:
                add_called = True
            if "commit" in cmd:
                commit_called = True
            if "push" in cmd:
                push_called = True
        return fake_run(cmd, *args, **kwargs)

    with mock.patch("subprocess.run", side_effect=track_calls):
        rc = build_dfb_json.write_and_ship(
            modified_edition, fake_repo["date"],
            dry_run=False, skip_deploy=True,
        )

    assert rc == 0
    assert add_called, "git add must be called for a changed file"
    assert commit_called, "git commit must be called for a changed file"
    assert push_called, "git push must be called for a changed file"
