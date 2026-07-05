#!/usr/bin/env python3
"""Tests for installing DailyBrief into Hermes cron."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import install_hermes_schedule as installer  # noqa: E402


def test_wrapper_turns_silent_marker_into_hermes_wake_gate():
    job = installer.HermesJob(
        name="brief-weekday-morning",
        schedule="0 7 * * 1-5",
        deliver="local",
        workdir=REPO_ROOT,
        repo_entrypoint=REPO_ROOT / "scripts/hermes_jobs/weekday_morning.py",
        hermes_script="dailybrief-weekday-morning.sh",
    )

    wrapper = installer.render_wrapper(job)

    assert "python3 " in wrapper
    assert str(job.repo_entrypoint) in wrapper
    assert '"$trimmed" = "[SILENT]"' in wrapper
    assert '{"wakeAgent": false}' in wrapper


def test_load_jobs_reads_manifest_contract():
    jobs = installer.load_jobs(REPO_ROOT / "ops/hermes_dailybrief_schedule.json")

    assert [job.name for job in jobs] == [
        "brief-weekday-morning",
        "brief-saturday",
        "brief-sunday",
    ]
    assert jobs[0].schedule == "0 7 * * 1-5"
    assert jobs[1].hermes_script == "dailybrief-saturday.sh"


def test_dry_run_does_not_write_wrapper_or_call_real_hermes(tmp_path, capsys):
    manifest = {
        "version": 1,
        "jobs": [
            {
                "name": "brief-weekday-morning",
                "schedule": "0 7 * * 1-5",
                "mode": "no-agent",
                "deliver": "local",
                "workdir": str(REPO_ROOT),
                "repoEntrypoint": "scripts/hermes_jobs/weekday_morning.py",
                "hermesScript": "dailybrief-weekday-morning.sh",
            }
        ],
    }
    manifest_path = tmp_path / "schedule.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rc = None
    argv = [
        "install_hermes_schedule.py",
        "--manifest",
        str(manifest_path),
        "--scripts-dir",
        str(tmp_path / "scripts"),
        "--hermes-bin",
        "missing-hermes-binary",
        "--dry-run",
    ]
    old_argv = sys.argv
    try:
        sys.argv = argv
        rc = installer.main()
    finally:
        sys.argv = old_argv

    assert rc == 0
    assert not (tmp_path / "scripts" / "dailybrief-weekday-morning.sh").exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["cron"][0]["command"][:4] == [
        "missing-hermes-binary",
        "cron",
        "edit",
        "brief-weekday-morning",
    ]
