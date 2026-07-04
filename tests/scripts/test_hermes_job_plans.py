#!/usr/bin/env python3
"""Tests for Hermes job wrapper command plans."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JOBS = REPO_ROOT / "scripts" / "hermes_jobs"

sys.path.insert(0, str(JOBS))

import _common as job_common  # noqa: E402


def _argvs(steps):
    return [step.argv for step in steps]


def test_weekday_plan_enriches_then_ships_existing_dfb_file():
    date_iso = "2026-07-06"

    steps = job_common.build_job_plan("weekday", date_iso, skip_deploy=False)
    argvs = _argvs(steps)

    assert [
        sys.executable,
        str(REPO_ROOT / "scripts" / "enrich_dfb_edition.py"),
        date_iso,
    ] in argvs
    assert [
        sys.executable,
        str(REPO_ROOT / "scripts" / "build_dfb_json.py"),
        "--skip-deploy",
        "--use-enriched",
        "--date",
        date_iso,
    ] in argvs
    assert ["vercel", "deploy", "--prod", "--non-interactive"] in argvs


def test_lifestyle_plan_publishes_existing_enriched_file_without_deploy(tmp_path, monkeypatch):
    date_iso = "2026-07-04"
    enriched = tmp_path / "out" / "lifestyle" / f"{date_iso}.json"
    enriched.parent.mkdir(parents=True)
    enriched.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(job_common, "REPO_ROOT", tmp_path)

    steps = job_common.build_job_plan("saturday", date_iso, skip_deploy=True)
    argvs = _argvs(steps)

    assert [
        sys.executable,
        str(tmp_path / "scripts" / "build_lifestyle_json.py"),
        "saturday",
        "--skip-deploy",
        "--use-enriched",
        "--date",
        date_iso,
    ] in argvs
    assert ["vercel", "deploy", "--prod", "--non-interactive"] not in argvs


def test_lifestyle_plan_builds_baseline_when_enriched_file_is_missing(tmp_path, monkeypatch):
    date_iso = "2026-07-05"
    monkeypatch.setattr(job_common, "REPO_ROOT", tmp_path)

    steps = job_common.build_job_plan("sunday", date_iso, skip_deploy=True)
    argvs = _argvs(steps)

    assert [
        sys.executable,
        str(tmp_path / "scripts" / "build_lifestyle_json.py"),
        "sunday",
        "--skip-deploy",
        "--date",
        date_iso,
    ] in argvs
    assert not any("--use-enriched" in argv for argv in argvs)
    assert ["vercel", "deploy", "--prod", "--non-interactive"] not in argvs


def test_sunday_dry_run_is_valid_without_preexisting_enriched_file(tmp_path, monkeypatch, capsys):
    date_iso = "2026-07-05"
    monkeypatch.setattr(job_common, "REPO_ROOT", tmp_path)

    rc = job_common.run_job(
        "sunday",
        date_iso=date_iso,
        skip_deploy=True,
        no_pull=True,
        dry_run=True,
    )

    assert rc == 0

    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["valid"] is True
    assert payload["issues"] == []
    assert payload["plannedSteps"][0]["argv"] == [
        sys.executable,
        str(tmp_path / "scripts" / "build_lifestyle_json.py"),
        "sunday",
        "--skip-deploy",
        "--date",
        date_iso,
    ]


def test_dry_run_prints_plan_without_executing_commands(capsys):
    """Dry-run mode should be safe: no subprocesses, only a plan envelope."""
    with mock.patch("subprocess.run") as mock_run:
        rc = job_common.run_job(
            "weekday",
            date_iso="2026-07-06",
            skip_deploy=False,
            no_pull=False,
            dry_run=True,
        )

    assert rc == 0
    assert mock_run.call_count == 0

    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["dryRun"] is True
    assert payload["job"] == "weekday"
    assert payload["date"] == "2026-07-06"
    assert any(
        step["name"] == "deploy website"
        and step["argv"] == ["vercel", "deploy", "--prod", "--non-interactive"]
        for step in payload["plannedSteps"]
    )
