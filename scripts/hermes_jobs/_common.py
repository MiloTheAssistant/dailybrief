#!/usr/bin/env python3
"""Shared command runner for Hermes-owned dailybrief jobs."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBSITE_DIR = REPO_ROOT.parent / "Milo" / "website"
PUBLIC_BASE = "https://daily-brief-tau.vercel.app"
RUN_LOG_PATH = REPO_ROOT / "logs" / "hermes_runs.jsonl"


@dataclass(frozen=True)
class Step:
    name: str
    argv: list[str]
    cwd: Path
    timeout_s: int
    allow_failure: bool = False


@dataclass
class StepResult:
    name: str
    argv: list[str]
    cwd: str
    returncode: int
    stdout_tail: str
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "returncode": self.returncode,
            "cwd": self.cwd,
            "stdoutTail": self.stdout_tail,
            "stderrTail": self.stderr_tail,
        }


def _py(script: str, *args: str) -> list[str]:
    return [sys.executable, str(REPO_ROOT / script), *args]


def _target_url(job: str, date_iso: str) -> str:
    if job == "weekday":
        return f"{PUBLIC_BASE}/"
    return f"{PUBLIC_BASE}/weekend/{date_iso}"


def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def _today_ct() -> str:
    return datetime.now(ZoneInfo("America/Chicago")).date().isoformat()


def build_job_plan(
    job: str,
    date_iso: str,
    *,
    skip_deploy: bool = False,
    no_pull: bool = False,
) -> list[Step]:
    """Return the exact command plan Hermes should execute for a job."""
    if job not in {"weekday", "saturday", "sunday"}:
        raise ValueError(f"unknown job: {job}")

    steps: list[Step] = []
    if not no_pull:
        steps.append(
            Step("sync dailybrief", ["git", "pull", "--ff-only"], REPO_ROOT, 60)
        )

    if job == "weekday":
        steps.extend(
            [
                Step(
                    "runtime preflight",
                    _py("scripts/build_dfb_json.py", "--check-deps"),
                    REPO_ROOT,
                    60,
                    allow_failure=True,
                ),
                Step(
                    "enrich dfb",
                    _py("scripts/enrich_dfb_edition.py", date_iso),
                    REPO_ROOT,
                    180,
                ),
                Step(
                    "publish dfb json",
                    _py(
                        "scripts/build_dfb_json.py",
                        "--skip-deploy",
                        "--use-enriched",
                        "--date",
                        date_iso,
                    ),
                    REPO_ROOT,
                    180,
                ),
            ]
        )
    else:
        lifestyle_args = [
            "scripts/build_lifestyle_json.py",
            job,
            "--skip-deploy",
        ]
        enriched = REPO_ROOT / "out" / "lifestyle" / f"{date_iso}.json"
        if enriched.exists():
            lifestyle_args.append("--use-enriched")
        lifestyle_args.extend(["--date", date_iso])
        steps.append(
            Step(
                "publish lifestyle json",
                _py(*lifestyle_args),
                REPO_ROOT,
                180,
            )
        )

    if not skip_deploy:
        steps.extend(
            [
                Step(
                    "sync website briefs",
                    ["npm", "run", "fetch-briefs"],
                    WEBSITE_DIR,
                    180,
                ),
                Step(
                    "deploy website",
                    ["vercel", "deploy", "--prod", "--non-interactive"],
                    WEBSITE_DIR,
                    900,
                ),
            ]
        )
    return steps


def _deployment_url(results: list[StepResult]) -> str | None:
    for result in reversed(results):
        if result.name != "deploy website":
            continue
        for line in reversed((result.stdout_tail or "").splitlines()):
            line = line.strip()
            if line.startswith("https://"):
                return line
    return None


def _append_run_log(envelope: dict) -> str | None:
    """Append a machine-readable run record without blocking publication."""
    record = dict(envelope)
    record["loggedAt"] = datetime.now(ZoneInfo("America/Chicago")).isoformat()
    try:
        RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        return str(exc)
    return None


def _planned_step(step: Step) -> dict:
    return {
        "name": step.name,
        "argv": step.argv,
        "cwd": str(step.cwd),
        "timeoutS": step.timeout_s,
        "allowFailure": step.allow_failure,
    }


def _validate_plan(job: str, date_iso: str, steps: list[Step]) -> list[str]:
    issues: list[str] = []
    if not REPO_ROOT.is_dir():
        issues.append(f"dailybrief repo missing: {REPO_ROOT}")
    if any(step.cwd == WEBSITE_DIR for step in steps) and not WEBSITE_DIR.is_dir():
        issues.append(f"website repo missing: {WEBSITE_DIR}")
    return issues


def run_steps(steps: list[Step]) -> tuple[str, list[StepResult]]:
    results: list[StepResult] = []
    for step in steps:
        print(f"[hermes_job] {step.name}: {' '.join(step.argv)}", file=sys.stderr)
        try:
            completed = subprocess.run(
                step.argv,
                cwd=step.cwd,
                capture_output=True,
                text=True,
                timeout=step.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            completed = subprocess.CompletedProcess(
                args=step.argv,
                returncode=124,
                stdout=e.stdout or "",
                stderr=e.stderr or f"timeout after {step.timeout_s}s",
            )

        result = StepResult(
            name=step.name,
            argv=step.argv,
            cwd=str(step.cwd),
            returncode=completed.returncode,
            stdout_tail=_tail(completed.stdout),
            stderr_tail=_tail(completed.stderr),
        )
        results.append(result)

        if completed.returncode == 2 and step.name == "enrich dfb":
            return "silent", results
        if completed.returncode != 0 and not step.allow_failure:
            return "failed", results
    return "published", results


def run_job(
    job: str,
    *,
    date_iso: str | None = None,
    skip_deploy: bool = False,
    no_pull: bool = False,
    dry_run: bool = False,
) -> int:
    date_iso = date_iso or _today_ct()
    steps = build_job_plan(
        job, date_iso, skip_deploy=skip_deploy, no_pull=no_pull
    )
    if dry_run:
        issues = _validate_plan(job, date_iso, steps)
        envelope = {
            "status": "dry_run",
            "dryRun": True,
            "valid": not issues,
            "issues": issues,
            "job": job,
            "kind": "dfb" if job == "weekday" else "lifestyle",
            "date": date_iso,
            "url": _target_url(job, date_iso),
            "deployed": False,
            "plannedSteps": [_planned_step(step) for step in steps],
        }
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
        return 0 if not issues else 1

    status, results = run_steps(steps)

    if status == "silent":
        envelope = {
            "status": status,
            "job": job,
            "kind": "dfb" if job == "weekday" else "lifestyle",
            "date": date_iso,
            "url": _target_url(job, date_iso),
            "deploymentUrl": None,
            "deployed": False,
            "preflight": "degraded"
            if any(r.name == "runtime preflight" and not r.ok for r in results)
            else "ok",
            "runLogPath": str(RUN_LOG_PATH),
            "steps": [r.as_dict() for r in results],
        }
        log_error = _append_run_log(envelope)
        if log_error:
            print(f"[hermes_job] run log write failed: {log_error}", file=sys.stderr)
        print("[SILENT]")
        return 0

    envelope = {
        "status": status,
        "job": job,
        "kind": "dfb" if job == "weekday" else "lifestyle",
        "date": date_iso,
        "url": _target_url(job, date_iso),
        "deploymentUrl": _deployment_url(results),
        "deployed": not skip_deploy and status == "published",
        "preflight": "degraded"
        if any(r.name == "runtime preflight" and not r.ok for r in results)
        else "ok",
        "runLogPath": str(RUN_LOG_PATH),
        "steps": [r.as_dict() for r in results],
    }
    log_error = _append_run_log(envelope)
    if log_error:
        envelope["runLogError"] = log_error
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0 if status == "published" else 1


def main_for(job: str) -> int:
    parser = argparse.ArgumentParser(description=f"Run Hermes dailybrief job: {job}.")
    parser.add_argument("--date", help="Override date (YYYY-MM-DD); default = today CT")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only; execute nothing")
    parser.add_argument("--skip-deploy", action="store_true", help="Publish JSON only")
    parser.add_argument("--no-pull", action="store_true", help="Skip git pull --ff-only")
    args = parser.parse_args()
    return run_job(
        job,
        date_iso=args.date,
        skip_deploy=args.skip_deploy,
        no_pull=args.no_pull,
        dry_run=args.dry_run,
    )
