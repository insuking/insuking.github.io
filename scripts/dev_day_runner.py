#!/usr/bin/env python3
"""Daily development automation runner.

Invoked by an external scheduler (systemd timer / cron / Task Scheduler) once
per day, per the project master spec (docs/MASTER_SPEC.md, section V-Y).

This script does NOT write phase code — a Claude Code session (or a human)
implements the day's phases beforehand. What it enforces is the mechanical,
non-negotiable part of the daily gate:

    git status check -> backup branch -> baseline gate (lint/typecheck/build)
    -> per-phase test verification -> commit (only phases that actually
    passed their own tests) -> daily report

A phase is marked complete only if backend tests tagged `@pytest.mark.<PHASE>`
(e.g. `pytest.mark.P1`) exist AND pass. Passing the generic full-suite gate is
NOT sufficient by itself — that would let a day claim phases with zero actual
test coverage, which is exactly what docs/MASTER_SPEC.md forbids ("절대로
테스트하지 않은 기능을 COMPLETE라고 표시하지 않는다"). This was a real bug in
an earlier version of this script (see docs/daily/DAY01.md) and must not
regress.

By default the phases attempted are `ROADMAP[day]` (both phases for that
day). Pass `--phases P1` to run/commit only a subset - useful when a day's
phases are being reviewed and landed one at a time rather than together.
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
    requested_phases: list[str]
    baseline_steps: list[StepResult] = field(default_factory=list)
    phase_steps: dict[str, StepResult] = field(default_factory=dict)

    @property
    def baseline_passed(self) -> bool:
        return all(step.passed for step in self.baseline_steps)

    @property
    def passed_phases(self) -> list[str]:
        return [p for p in self.requested_phases if self.phase_steps[p].passed]

    @property
    def failed_phases(self) -> list[str]:
        return [p for p in self.requested_phases if not self.phase_steps[p].passed]

    @property
    def all_requested_passed(self) -> bool:
        return self.baseline_passed and not self.failed_phases


def run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    return proc.returncode == 0, output


def backend_python() -> str:
    venv_python = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


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


def run_baseline_gate() -> list[StepResult]:
    """Whole-repo quality gate: must always be clean, independent of phase."""
    backend_dir = REPO_ROOT / "backend"
    frontend_dir = REPO_ROOT / "frontend"
    python = backend_python()

    # "." only covers backend/ - tests/backend lives one level up (P0's
    # top-level tests/ layout) and ruff/mypy won't walk out of cwd on their
    # own, so it must be passed explicitly or it silently goes unchecked.
    steps = []
    ok, out = run([python, "-m", "ruff", "check", ".", "../tests/backend"], backend_dir)
    steps.append(StepResult("backend: ruff", ok, out))
    ok, out = run([python, "-m", "mypy", "app", "../tests/backend"], backend_dir)
    steps.append(StepResult("backend: mypy", ok, out))
    ok, out = run([python, "-m", "pytest", "-q"], backend_dir)
    steps.append(StepResult("backend: full pytest suite", ok, out))
    ok, out = run(["npm", "run", "lint"], frontend_dir)
    steps.append(StepResult("frontend: lint", ok, out))
    ok, out = run(["npm", "run", "build"], frontend_dir)
    steps.append(StepResult("frontend: build", ok, out))
    return steps


def run_phase_gate(phase: str) -> StepResult:
    """A phase is only real if tests tagged for it exist and pass.

    `pytest -m <marker>` exits non-zero both when marked tests fail and when
    the marker matches zero tests ("no tests ran") - either way this phase
    is not verified and must not be marked complete.
    """
    backend_dir = REPO_ROOT / "backend"
    python = backend_python()
    ok, out = run([python, "-m", "pytest", "-q", "-m", phase], backend_dir)
    if "no tests ran" in out.lower() or "collected 0 items" in out.lower():
        ok = False
        out += "\n[runner] no tests tagged for this phase - cannot mark it complete."
    return StepResult(f"phase gate: {phase}", ok, out)


def write_daily_report(report: RunReport) -> Path:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"DAY{report.day:02d}.md"

    # Days are sometimes gated one phase at a time (e.g. reviewing P1 before
    # starting P2) rather than in one run. Each run appends its own "## Run
    # at <timestamp>" section instead of overwriting the file, so an earlier
    # phase's detailed record survives a later run for the same day.
    is_new_file = not path.exists()

    lines = []
    if is_new_file:
        lines.append(f"# Day {report.day} report")
        lines.append("")

    lines.append(f"## Run at {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append(f"Requested phases: {', '.join(report.requested_phases)}")
    lines.append(f"Baseline gate: {'PASS' if report.baseline_passed else 'FAIL'}")
    lines.append(f"Phases completed this run: {', '.join(report.passed_phases) or '(none)'}")
    lines.append(f"Phases NOT completed this run: {', '.join(report.failed_phases) or '(none)'}")
    lines.append("")
    lines.append("### Baseline steps")
    lines.append("")
    for step in report.baseline_steps:
        status = "PASS" if step.passed else "FAIL"
        lines.append(f"#### {step.name} - {status}")
        if step.output.strip():
            lines.append("```")
            lines.append(step.output.strip()[:4000])
            lines.append("```")
        lines.append("")

    lines.append("### Per-phase verification")
    lines.append("")
    for phase in report.requested_phases:
        step = report.phase_steps[phase]
        status = "PASS" if step.passed else "FAIL"
        lines.append(f"#### {phase} - {status}")
        if step.output.strip():
            lines.append("```")
            lines.append(step.output.strip()[:4000])
            lines.append("```")
        lines.append("")

    with path.open("a") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=int, required=True, help="Day number (0-11)")
    parser.add_argument(
        "--phases",
        type=str,
        default=None,
        help="Comma-separated subset of the day's phases to gate/commit "
        "(default: all phases for --day per the roadmap)",
    )
    parser.add_argument(
        "--skip-backup-branch",
        action="store_true",
        help="Skip creating a git backup branch (useful for local dry runs)",
    )
    args = parser.parse_args()

    if args.day not in ROADMAP:
        print(f"Unknown day {args.day}. Valid days: {sorted(ROADMAP)}", file=sys.stderr)
        return 2

    day_phases = ROADMAP[args.day]
    requested_phases = args.phases.split(",") if args.phases else day_phases
    unknown = [p for p in requested_phases if p not in day_phases]
    if unknown:
        print(f"Phases {unknown} are not part of day {args.day} ({day_phases})", file=sys.stderr)
        return 2

    report = RunReport(day=args.day, requested_phases=requested_phases)

    report.baseline_steps.append(check_git_status())
    if not args.skip_backup_branch:
        report.baseline_steps.append(create_backup_branch(args.day))
    report.baseline_steps.extend(run_baseline_gate())

    for phase in requested_phases:
        report.phase_steps[phase] = run_phase_gate(phase)

    report_path = write_daily_report(report)
    print(f"Daily report written to {report_path}")

    if not report.baseline_passed:
        print("BASELINE GATE FAILED - nothing marked complete. See report.", file=sys.stderr)
        return 1

    if not report.passed_phases:
        print(f"No phase passed its gate ({report.failed_phases}). Nothing committed.", file=sys.stderr)
        return 1

    state = load_state()
    for phase in report.passed_phases:
        if phase not in state["completed_phases"]:
            state["completed_phases"].append(phase)
    state["blocked"] = False
    state["last_test_result"] = "PASS" if report.all_requested_passed else "PARTIAL"

    if set(day_phases).issubset(set(state["completed_phases"])):
        state["current_day"] = args.day
        next_day = args.day + 1
        state["active_phase"] = ROADMAP.get(next_day, ["DONE"])[0]
    else:
        remaining = [p for p in day_phases if p not in state["completed_phases"]]
        state["active_phase"] = remaining[0] if remaining else state.get("active_phase")

    save_state(state)

    git("add", "-A")
    _, staged = git("diff", "--cached", "--name-only")
    if staged.strip():
        commit_message = f"Day {args.day}: {', '.join(report.passed_phases)} gate passed"
        commit_ok, commit_out = git("commit", "-m", commit_message)
        if not commit_ok:
            print(f"WARNING: gate passed but commit failed:\n{commit_out}", file=sys.stderr)
            return 1
    else:
        print("Nothing to commit (working tree already matches gated state).")

    ok, commit_sha = git("rev-parse", "HEAD")
    state["last_verified_commit"] = commit_sha.strip() if ok else None
    save_state(state)

    print(f"Phases completed this run: {report.passed_phases}")
    if report.failed_phases:
        print(f"Phases NOT completed (no/failing tests): {report.failed_phases}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
