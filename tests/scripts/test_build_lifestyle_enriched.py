#!/usr/bin/env python3
"""Tests for publishing an already-enriched lifestyle edition."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import build_lifestyle_json  # noqa: E402


def test_use_enriched_reads_existing_file_without_reassembling(tmp_path, monkeypatch, capsys):
    """--use-enriched must ship the existing JSON instead of rebuilding it."""
    out_dir = tmp_path / "out" / "lifestyle"
    out_dir.mkdir(parents=True)
    date_iso = "2026-07-04"
    enriched = {
        "date": date_iso,
        "weekday": "Saturday",
        "kind": "lifestyle",
        "generatedAt": "2026-07-04T14:00:00+00:00",
        "zip": "63025",
        "location": {"label": "Eureka, MO", "lat": 38.5017, "lon": -90.6276},
        "pillars": {"life": {"oneThing": "Keep this enriched text."}},
    }
    (out_dir / f"{date_iso}.json").write_text(
        json.dumps(enriched), encoding="utf-8"
    )

    monkeypatch.setattr(build_lifestyle_json.pc, "OUT_DIR", out_dir)

    def fail_assemble(*_args, **_kwargs):
        raise AssertionError("assemble() should not run when --use-enriched is set")

    captured: dict = {}

    def fake_write_and_ship(edition, day, today_iso, dry_run, skip_deploy):
        captured.update(
            {
                "edition": edition,
                "day": day,
                "today_iso": today_iso,
                "dry_run": dry_run,
                "skip_deploy": skip_deploy,
            }
        )
        return 0

    monkeypatch.setattr(build_lifestyle_json.pc, "assemble", fail_assemble)
    monkeypatch.setattr(build_lifestyle_json.pc, "write_and_ship", fake_write_and_ship)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_lifestyle_json.py",
            "saturday",
            "--date",
            date_iso,
            "--use-enriched",
            "--skip-deploy",
        ],
    )

    rc = build_lifestyle_json.main()

    assert rc == 0
    assert captured == {
        "edition": enriched,
        "day": "saturday",
        "today_iso": date_iso,
        "dry_run": False,
        "skip_deploy": True,
    }
    assert json.loads(capsys.readouterr().out) == enriched


def test_use_enriched_missing_file_exits_without_reassembling(tmp_path, monkeypatch):
    """A missing enriched file should fail clearly instead of rebuilding."""
    out_dir = tmp_path / "out" / "lifestyle"
    out_dir.mkdir(parents=True)
    monkeypatch.setattr(build_lifestyle_json.pc, "OUT_DIR", out_dir)
    monkeypatch.setattr(
        build_lifestyle_json.pc,
        "assemble",
        lambda *_args, **_kwargs: pytest.fail("assemble() should not run"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_lifestyle_json.py",
            "sunday",
            "--date",
            "2026-07-05",
            "--use-enriched",
        ],
    )

    assert build_lifestyle_json.main() == 3
