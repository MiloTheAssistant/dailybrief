#!/usr/bin/env python3
"""Install or update Hermes cron jobs for the DailyBrief publisher."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "ops" / "hermes_dailybrief_schedule.json"


@dataclass(frozen=True)
class HermesJob:
    name: str
    schedule: str
    deliver: str
    workdir: Path
    repo_entrypoint: Path
    hermes_script: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HermesJob":
        missing = [
            key
            for key in (
                "name",
                "schedule",
                "deliver",
                "workdir",
                "repoEntrypoint",
                "hermesScript",
            )
            if not raw.get(key)
        ]
        if missing:
            raise ValueError(f"job is missing required fields: {', '.join(missing)}")
        if raw.get("mode") != "no-agent":
            raise ValueError(f"job {raw['name']!r} must use mode='no-agent'")
        script = str(raw["hermesScript"])
        if script.startswith(("/", "~")) or ".." in Path(script).parts:
            raise ValueError(
                f"job {raw['name']!r} has unsafe hermesScript: {script!r}"
            )
        workdir = Path(raw["workdir"]).expanduser()
        return cls(
            name=str(raw["name"]),
            schedule=str(raw["schedule"]),
            deliver=str(raw["deliver"]),
            workdir=workdir,
            repo_entrypoint=workdir / str(raw["repoEntrypoint"]),
            hermes_script=script,
        )


def load_jobs(manifest_path: Path) -> list[HermesJob]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError(f"unsupported manifest version: {manifest.get('version')!r}")
    raw_jobs = manifest.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ValueError("manifest must contain a non-empty jobs list")
    return [HermesJob.from_dict(raw) for raw in raw_jobs]


def render_wrapper(job: HermesJob) -> str:
    """Return a Hermes-safe bash wrapper for a repo-owned entrypoint."""
    workdir = shlex.quote(str(job.workdir))
    entrypoint = shlex.quote(str(job.repo_entrypoint))
    return f"""#!/usr/bin/env bash
set -u

cd {workdir}

output="$(python3 {entrypoint} 2> >(cat >&2))"
rc=$?

if [ "$rc" -ne 0 ]; then
  if [ -n "$output" ]; then
    printf '%s\\n' "$output"
  fi
  exit "$rc"
fi

trimmed="$(printf '%s' "$output" | tr -d '[:space:]')"
if [ "$trimmed" = "[SILENT]" ]; then
  printf '{{"wakeAgent": false}}\\n'
  exit 0
fi

printf '%s\\n' "$output"
"""


def install_wrappers(
    jobs: list[HermesJob], scripts_dir: Path, *, dry_run: bool
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for job in jobs:
        destination = scripts_dir / job.hermes_script
        content = render_wrapper(job)
        results.append(
            {
                "job": job.name,
                "script": str(destination),
                "entrypoint": str(job.repo_entrypoint),
                "changed": not destination.exists()
                or destination.read_text(encoding="utf-8") != content,
            }
        )
        if dry_run:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        mode = destination.stat().st_mode
        destination.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return results


def _run(argv: list[str], *, dry_run: bool) -> subprocess.CompletedProcess[str]:
    if dry_run:
        return subprocess.CompletedProcess(argv, 0, "", "")
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


def _job_not_found(completed: subprocess.CompletedProcess[str]) -> bool:
    combined = f"{completed.stdout}\n{completed.stderr}"
    return "Job not found" in combined or "not found" in combined


def install_cron_jobs(
    jobs: list[HermesJob],
    *,
    hermes_bin: str,
    dry_run: bool,
    resume: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for job in jobs:
        edit_cmd = [
            hermes_bin,
            "cron",
            "edit",
            job.name,
            "--schedule",
            job.schedule,
            "--prompt",
            "",
            "--clear-skills",
            "--script",
            job.hermes_script,
            "--no-agent",
            "--workdir",
            str(job.workdir),
            "--deliver",
            job.deliver,
            "--name",
            job.name,
        ]
        completed = _run(edit_cmd, dry_run=dry_run)
        action = "updated"
        command = edit_cmd
        if completed.returncode != 0 and _job_not_found(completed):
            create_cmd = [
                hermes_bin,
                "cron",
                "create",
                job.schedule,
                "--script",
                job.hermes_script,
                "--no-agent",
                "--workdir",
                str(job.workdir),
                "--deliver",
                job.deliver,
                "--name",
                job.name,
            ]
            completed = _run(create_cmd, dry_run=dry_run)
            action = "created"
            command = create_cmd

        resume_result: subprocess.CompletedProcess[str] | None = None
        if completed.returncode == 0 and resume:
            resume_result = _run(
                [hermes_bin, "cron", "resume", job.name],
                dry_run=dry_run,
            )

        results.append(
            {
                "job": job.name,
                "action": action,
                "schedule": job.schedule,
                "script": job.hermes_script,
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "resumeReturncode": None
                if resume_result is None
                else resume_result.returncode,
                "resumeStdout": None
                if resume_result is None
                else resume_result.stdout.strip(),
                "resumeStderr": None
                if resume_result is None
                else resume_result.stderr.strip(),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install DailyBrief wrapper scripts and Hermes cron jobs."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--hermes-bin", default=os.environ.get("HERMES_BIN", "hermes"))
    parser.add_argument(
        "--scripts-dir",
        default=os.path.expanduser("~/.hermes/scripts"),
        help="Hermes scripts directory; default: ~/.hermes/scripts",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume jobs after create/update.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    scripts_dir = Path(args.scripts_dir).expanduser().resolve()
    jobs = load_jobs(manifest_path)

    for job in jobs:
        if not job.workdir.is_dir():
            raise SystemExit(f"workdir does not exist for {job.name}: {job.workdir}")
        if not job.repo_entrypoint.is_file():
            raise SystemExit(
                f"entrypoint does not exist for {job.name}: {job.repo_entrypoint}"
            )

    wrappers = install_wrappers(jobs, scripts_dir, dry_run=args.dry_run)
    cron = install_cron_jobs(
        jobs,
        hermes_bin=args.hermes_bin,
        dry_run=args.dry_run,
        resume=not args.no_resume,
    )
    failed = [
        item
        for item in cron
        if item["returncode"] != 0
        or (
            item["resumeReturncode"] is not None
            and item["resumeReturncode"] != 0
        )
    ]
    envelope = {
        "status": "dry_run" if args.dry_run else ("failed" if failed else "installed"),
        "manifest": str(manifest_path),
        "scriptsDir": str(scripts_dir),
        "wrappers": wrappers,
        "cron": cron,
    }
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
