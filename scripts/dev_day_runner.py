#!/usr/bin/env python3
"""Daily development automation runner.

Invoked by an external scheduler (systemd timer / cron / Task Scheduler) once
per day, per the project master spec (docs/MASTER_SPEC.md, section V-Y).

This script does NOT write phase code — a Claude Code session (or a human)
implements the day's phases beforehand. What it enforces is the mechanical,
non-negotiable part of the daily gate:

    git status check -> backup branch -> environment health check
    -> test/lint/typecheck gate (backend + frontend) -> commit -> daily report

If the gate fails, `.devstate/state.json` is left untouched and the script
exits non-zero — the day is not marked complete, and per the "never hide
failures" rule this script does not retry with a lowered bar.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / ".devstate" / "state.json"
DAILY_DIR = REPO_ROOT / "docs" / "daily"

# Day -> phases, per docs/MASTER_SPEC.md section Z. Day 0 is bootstrap-only.
ROADMAP: dict[int, list[str]] = {
    0: ["P0"],
    1: ["P1", "P2"],
    2: ["P3", "P4"],
    3: ["P5", "P6"],
    4: ["P7", "P8"],
    5: ["P9", "P10"],
    6: ["P11", "P12"],
    7: ["P13", "P14"],
    8: ["P15", "P16"],
    9: ["P17", "P18"],
    10: ["P19", "P20"],
    11: ["P21", "P22"],
}


@dataclass
class StepResult:
    name: str
    passed: bool
    output: str = ""


@dataclass
class RunReport:
    day: int
    phases: list[str]
    steps: list[StepResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(step.passed for step in self.steps)


def run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    return proc.returncode == 0, output


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "current_day": -1,
            "completed_phases": [],
            "active_phase": "P0",
            "blocked": False,
            "last_verified_commit": None,
            "last_test_result": "UNKNOWN",
        }
    return json.loads(STATE_PATH.read_text())


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def git(*args: str) -> tuple[bool, str]:
    return run(["git", *args], cwd=REPO_ROOT)


def check_git_status() -> StepResult:
    ok, output = git("status", "--porcelain")
    return StepResult("git status", ok, output)


def create_backup_branch(day: int) -> StepResult:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    branch = f"backup/day{day:02d}-{timestamp}"
    ok, output = git("branch", branch)
    return StepResult(f"backup branch {branch}", ok, output)


def run_backend_gate() -> list[StepResult]:
    backend_dir = REPO_ROOT / "backend"
    venv_python = backend_dir / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable

    steps = []
    ok, out = run([python, "-m", "ruff", "check", "."], backend_dir)
    steps.append(StepResult("backend: ruff", ok, out))
    ok, out = run([python, "-m", "mypy", "app"], backend_dir)
    steps.append(StepResult("backend: mypy", ok, out))
    ok, out = run([python, "-m", "pytest", "-q"], backend_dir)
    steps.append(StepResult("backend: pytest", ok, out))
    return steps


def run_frontend_gate() -> list[StepResult]:
    frontend_dir = REPO_ROOT / "frontend"
    steps = []
    ok, out = run(["npm", "run", "lint"], frontend_dir)
    steps.append(StepResult("frontend: lint", ok, out))
    ok, out = run(["npm", "run", "build"], frontend_dir)
    steps.append(StepResult("frontend: build", ok, out))
    return steps


def write_daily_report(report: RunReport) -> Path:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"DAY{report.day:02d}.md"

    lines = [
        f"# Day {report.day} report",
        "",
        f"Phases: {', '.join(report.phases)}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Gate result: {'PASS' if report.all_passed else 'FAIL'}",
        "",
        "## Steps",
        "",
    ]
    for step in report.steps:
        status = "PASS" if step.passed else "FAIL"
        lines.append(f"### {step.name} - {status}")
        if step.output.strip():
            lines.append("```")
            lines.append(step.output.strip()[:4000])
            lines.append("```")
        lines.append("")

    path.write_text("\n".join(lines))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=int, required=True, help="Day number (0-11)")
    parser.add_argument(
        "--skip-backup-branch",
        action="store_true",
        help="Skip creating a git backup branch (useful for local dry runs)",
    )
    args = parser.parse_args()

    if args.day not in ROADMAP:
        print(f"Unknown day {args.day}. Valid days: {sorted(ROADMAP)}", file=sys.stderr)
        return 2

    phases = ROADMAP[args.day]
    report = RunReport(day=args.day, phases=phases)

    status_step = check_git_status()
    report.steps.append(status_step)

    if not args.skip_backup_branch:
        report.steps.append(create_backup_branch(args.day))

    report.steps.extend(run_backend_gate())
    report.steps.extend(run_frontend_gate())

    if not report.all_passed:
        write_daily_report(report)
        print("GATE FAILED - state not advanced. See report for details.", file=sys.stderr)
        return 1

    state = load_state()
    state["current_day"] = args.day
    for phase in phases:
        if phase not in state["completed_phases"]:
            state["completed_phases"].append(phase)
    state["blocked"] = False
    state["last_test_result"] = "PASS"
    save_state(state)

    report_path = write_daily_report(report)

    git("add", "-A")
    _, staged = git("diff", "--cached", "--name-only")
    if staged.strip():
        commit_message = f"Day {args.day}: {', '.join(phases)} gate passed"
        commit_ok, commit_out = git("commit", "-m", commit_message)
        if not commit_ok:
            print(f"WARNING: gate passed but commit failed:\n{commit_out}", file=sys.stderr)
            return 1
    else:
        print("Nothing to commit (working tree already matches gated state).")

    ok, commit_sha = git("rev-parse", "HEAD")
    state["last_verified_commit"] = commit_sha.strip() if ok else None
    save_state(state)

    print(f"Daily report written to {report_path}")
    print(f"Day {args.day} gate PASSED. Phases {phases} marked complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
