#!/usr/bin/env python3
"""Tests for lifestyle publish git handoff behavior."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import _publish_common as publish_common  # noqa: E402


def test_write_and_ship_force_adds_ignored_out_files(tmp_path, monkeypatch):
    """out/ is gitignored, so lifestyle JSON must be force-added."""
    fake_repo = tmp_path / "repo"
    fake_out = fake_repo / "out" / "lifestyle"
    fake_out.mkdir(parents=True)
    (fake_repo / "out" / "dfb").mkdir(parents=True)
    (fake_repo / ".gitignore").write_text("out\n", encoding="utf-8")

    monkeypatch.setattr(publish_common, "REPO_ROOT", fake_repo)
    monkeypatch.setattr(publish_common, "OUT_DIR", fake_out)

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(publish_common.subprocess, "run", fake_run)

    rc = publish_common.write_and_ship(
        {"date": "2026-07-05", "kind": "lifestyle", "sections": {}},
        "sunday",
        "2026-07-05",
        dry_run=False,
        skip_deploy=True,
    )

    assert rc == 0
    assert calls[0] == [
        "git",
        "add",
        "-f",
        "out/lifestyle/2026-07-05.json",
        "out/manifest.json",
    ]

