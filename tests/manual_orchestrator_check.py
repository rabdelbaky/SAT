"""Manual orchestrator checks for Session 7 (orchestrator.py).

Run as:
    python tests/manual_orchestrator_check.py

Prints one PASS/FAIL line per check.  All checks invoke pre_llm_checks.main()
directly (no subprocess) against fixture folders.  The report JSON written to a
temp directory is then read and assertions are made on its contents.

Exit code: 0 if all checks pass, 1 if any fail.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure the repo root is on the path
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import pre_llm_checks  # noqa: E402

_FIXTURES = _REPO_ROOT / "tests" / "fixtures"

_PASS = "PASS"
_FAIL = "FAIL"
_results: list[tuple[int, str, str]] = []


def _check(num: int, description: str, *, ok: bool, detail: str = "") -> None:
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}")
    _results.append((num, label, description))


def _run_fixture(
    fixture_name: str,
    extra_args: list[str] | None = None,
    tmp_dir: Path | None = None,
) -> tuple[int, dict | None]:
    """Run pre_llm_checks.main() against *fixture_name* and return (exit_code, report).

    The report is written to *tmp_dir* so fixture folders are never polluted.
    .pre-llm/logs will be created in CWD (the repo root when run normally).
    """
    fixture_path = _FIXTURES / fixture_name
    if tmp_dir is None:
        raise ValueError("tmp_dir required")

    # Use a unique name per fixture+args combo to avoid stale reads
    safe_name = fixture_name.replace("/", "_").replace("\\", "_")
    extra_tag = "_".join(extra_args or []).replace("-", "").replace(",", "_")
    report_filename = f"report_{safe_name}_{extra_tag}.json"
    report_path = tmp_dir / report_filename

    # Remove stale report from a previous run of the same check
    if report_path.exists():
        report_path.unlink()

    argv = [
        "--path",
        str(fixture_path),
        "--output",
        str(report_path),
    ]
    if extra_args:
        argv.extend(extra_args)

    try:
        exit_code = pre_llm_checks.main(argv)
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [internal crash: {exc}]", file=sys.stderr)
        exit_code = 2

    report: dict | None = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            report = None

    return exit_code, report


# ---------------------------------------------------------------------------
# Report inspection helpers
# ---------------------------------------------------------------------------


def _stage_statuses(report: dict, project_index: int = 0) -> dict[str, str]:
    """Return {stage: status} for the project at *project_index*."""
    try:
        cmds = report["projects"][project_index]["commands"]
    except (KeyError, IndexError, TypeError):
        return {}
    result: dict[str, str] = {}
    for cmd in cmds:
        stage = cmd.get("stage")
        if stage:
            result[stage] = cmd.get("status", "unknown")
    return result


def _stage_reasons(report: dict, project_index: int = 0) -> dict[str, str | None]:
    """Return {stage: reason} for the project at *project_index*."""
    try:
        cmds = report["projects"][project_index]["commands"]
    except (KeyError, IndexError, TypeError):
        return {}
    result: dict[str, str | None] = {}
    for cmd in cmds:
        stage = cmd.get("stage")
        if stage:
            result[stage] = cmd.get("reason")
    return result


def _project_commands(report: dict, project_index: int = 0) -> list[dict]:
    """Return the commands list for the project at *project_index*."""
    try:
        return report["projects"][project_index]["commands"]
    except (KeyError, IndexError, TypeError):
        return []


def _find_project(report: dict, path_fragment: str) -> dict | None:
    """Return the first project entry whose path contains *path_fragment*."""
    for proj in report.get("projects", []):
        if path_fragment in (proj.get("path") or ""):
            return proj
    return None


def _project_stage_statuses(proj: dict) -> dict[str, str]:
    """Return {stage: status} from a project's commands list."""
    result: dict[str, str] = {}
    for cmd in (proj or {}).get("commands", []):
        stage = cmd.get("stage")
        if stage:
            result[stage] = cmd.get("status", "unknown")
    return result


def _project_stage_reasons(proj: dict) -> dict[str, str | None]:
    """Return {stage: reason} from a project's commands list."""
    result: dict[str, str | None] = {}
    for cmd in (proj or {}).get("commands", []):
        stage = cmd.get("stage")
        if stage:
            result[stage] = cmd.get("reason")
    return result


def _project_warnings(report: dict, project_index: int = 0) -> list[str]:
    """Return the warnings list for the project at *project_index*."""
    try:
        return report["projects"][project_index].get("warnings", [])
    except (KeyError, IndexError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def run_checks() -> int:
    # Run from repo root so .pre-llm/logs lands there, not in fixtures.
    os.chdir(_REPO_ROOT)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # ==================================================================
        # FIXTURE: build-gate
        # ==================================================================

        exit_code, report = _run_fixture("build-gate", tmp_dir=tmp)
        statuses = _stage_statuses(report) if report else {}
        reasons = _stage_reasons(report) if report else {}

        # ------------------------------------------------------------------
        # Check 1: build fails → exit code 1
        # ------------------------------------------------------------------
        _check(
            1,
            "build-gate: exit code is 1 when build fails",
            ok=exit_code == 1,
            detail=f"got exit_code={exit_code}",
        )

        # ------------------------------------------------------------------
        # Check 2: build stage ran and has status 'fail'
        # ------------------------------------------------------------------
        _check(
            2,
            "build-gate: build stage ran and has status='fail'",
            ok=statuses.get("build") == "fail",
            detail=f"stages={statuses}",
        )

        # ------------------------------------------------------------------
        # Check 3: lint/tests/coverage skipped with reason='build_gate'
        # (not vacuous: must be exactly 'skipped' AND reason='build_gate')
        # ------------------------------------------------------------------
        _check(
            3,
            "build-gate: lint/tests/coverage skipped with reason='build_gate'",
            ok=(
                statuses.get("lint") == "skipped"
                and reasons.get("lint") == "build_gate"
                and statuses.get("tests") == "skipped"
                and reasons.get("tests") == "build_gate"
                and statuses.get("coverage") == "skipped"
                and reasons.get("coverage") == "build_gate"
            ),
            detail=f"statuses={statuses} reasons={reasons}",
        )

        # ------------------------------------------------------------------
        # Check 4: report is written with schema_version and project_count=1
        # ------------------------------------------------------------------
        _check(
            4,
            "build-gate: report written, schema_version='1.0', project_count=1",
            ok=(
                report is not None
                and report.get("schema_version") == "1.0"
                and report.get("summary", {}).get("project_count") == 1
            ),
            detail=f"report={report.get('summary') if report else None}",
        )

        # ------------------------------------------------------------------
        # Check 5: build-gate --lint-anyway → lint ran and passed
        # ------------------------------------------------------------------
        _, report5 = _run_fixture(
            "build-gate", extra_args=["--lint-anyway"], tmp_dir=tmp
        )
        statuses5 = _stage_statuses(report5) if report5 else {}
        reasons5 = _stage_reasons(report5) if report5 else {}
        _check(
            5,
            "build-gate --lint-anyway: lint ran and passed",
            ok=statuses5.get("lint") == "pass",
            detail=f"lint={statuses5.get('lint')} all={statuses5}",
        )

        # ------------------------------------------------------------------
        # Check 6: build-gate --lint-anyway → tests/coverage skipped with
        # reason='build_gate' (not vacuous: must have that specific reason)
        # ------------------------------------------------------------------
        _check(
            6,
            "build-gate --lint-anyway: tests/coverage skipped reason='build_gate'",
            ok=(
                statuses5.get("tests") == "skipped"
                and reasons5.get("tests") == "build_gate"
                and statuses5.get("coverage") == "skipped"
                and reasons5.get("coverage") == "build_gate"
            ),
            detail=f"tests={statuses5.get('tests')} reason={reasons5.get('tests')} "
            f"coverage={statuses5.get('coverage')} reason={reasons5.get('coverage')}",
        )

        # ------------------------------------------------------------------
        # Check 7: build-gate --steps lint,tests → gate off, both pass
        # ------------------------------------------------------------------
        _, report7 = _run_fixture(
            "build-gate", extra_args=["--steps", "lint,tests"], tmp_dir=tmp
        )
        statuses7 = _stage_statuses(report7) if report7 else {}
        _check(
            7,
            "build-gate --steps lint,tests: gate off, lint and tests pass",
            ok=(statuses7.get("lint") == "pass" and statuses7.get("tests") == "pass"),
            detail=f"statuses={statuses7}",
        )

        # ==================================================================
        # FIXTURE: missing-deps
        # ==================================================================

        exit_code8, report8 = _run_fixture("missing-deps", tmp_dir=tmp)
        statuses8 = _stage_statuses(report8) if report8 else {}
        warnings8 = _project_warnings(report8) if report8 else []

        # ------------------------------------------------------------------
        # Check 8: missing-deps → build passed, tests ran (not vacuous: must
        # show project_count=1 and build actually executed)
        # ------------------------------------------------------------------
        _check(
            8,
            "missing-deps: report has 1 project and build ran (status='pass')",
            ok=(
                report8 is not None
                and report8.get("summary", {}).get("project_count") == 1
                and statuses8.get("build") == "pass"
            ),
            detail=f"project_count={report8.get('summary', {}).get('project_count') if report8 else None} "
            f"build={statuses8.get('build')}",
        )

        # ------------------------------------------------------------------
        # Check 9: tests stage has status 'dependencies_missing'
        # ------------------------------------------------------------------
        _check(
            9,
            "missing-deps: tests stage status='dependencies_missing'",
            ok=statuses8.get("tests") == "dependencies_missing",
            detail=f"stages={statuses8}",
        )

        # ------------------------------------------------------------------
        # Check 10: exit code is 0 (dependencies_missing is a warning)
        # ------------------------------------------------------------------
        _check(
            10,
            "missing-deps: exit code is 0 (dep-missing is warning, not failure)",
            ok=exit_code8 == 0,
            detail=f"got exit_code={exit_code8}",
        )

        # ==================================================================
        # FIXTURE: no-linter
        # ==================================================================

        exit_code11, report11 = _run_fixture("no-linter", tmp_dir=tmp)
        statuses11 = _stage_statuses(report11) if report11 else {}

        # ------------------------------------------------------------------
        # Check 11: build and tests ran and passed (not vacuous: commands
        # actually executed, not skipped)
        # ------------------------------------------------------------------
        _check(
            11,
            "no-linter: build and tests ran and passed (status='pass')",
            ok=(
                statuses11.get("build") == "pass" and statuses11.get("tests") == "pass"
            ),
            detail=f"build={statuses11.get('build')} tests={statuses11.get('tests')}",
        )

        # ------------------------------------------------------------------
        # Check 12: lint stage has status 'no_linter_configured'
        # ------------------------------------------------------------------
        _check(
            12,
            "no-linter: lint stage status='no_linter_configured'",
            ok=statuses11.get("lint") == "no_linter_configured",
            detail=f"stages={statuses11}",
        )

        # ------------------------------------------------------------------
        # Check 13: exit code is 0 (no_linter_configured is not a failure)
        # ------------------------------------------------------------------
        _check(
            13,
            "no-linter: exit code is 0",
            ok=exit_code11 == 0,
            detail=f"got exit_code={exit_code11}",
        )

        # ==================================================================
        # FIXTURE: nothing-to-run
        # ==================================================================

        exit_code14, report14 = _run_fixture("nothing-to-run", tmp_dir=tmp)

        # ------------------------------------------------------------------
        # Check 14: report has 1 project with nothing_to_run warning
        # (not vacuous: project must appear with the specific warning)
        # ------------------------------------------------------------------
        nothing_warning_ok = False
        if report14:
            w14 = _project_warnings(report14)
            n_proj = report14.get("summary", {}).get("project_count", 0)
            nothing_warning_ok = n_proj == 1 and "nothing_to_run" in w14
        _check(
            14,
            "nothing-to-run: 1 project in report with 'nothing_to_run' warning",
            ok=nothing_warning_ok,
            detail=(
                f"project_count={report14.get('summary', {}).get('project_count') if report14 else None} "
                f"warnings={_project_warnings(report14) if report14 else None}"
            ),
        )

        # ------------------------------------------------------------------
        # Check 15: all stages skipped with reason='nothing_to_run'
        # (not vacuous: reason must specifically be 'nothing_to_run')
        # ------------------------------------------------------------------
        reasons14 = _stage_reasons(report14) if report14 else {}
        statuses14 = _stage_statuses(report14) if report14 else {}
        all_nothing = (
            bool(statuses14)
            and all(s == "skipped" for s in statuses14.values())
            and all(r == "nothing_to_run" for r in reasons14.values())
        )
        _check(
            15,
            "nothing-to-run: all stages skipped with reason='nothing_to_run'",
            ok=all_nothing,
            detail=f"statuses={statuses14} reasons={reasons14}",
        )

        # ------------------------------------------------------------------
        # Check 16: exit code is 0 (nothing_to_run is a warning)
        # ------------------------------------------------------------------
        _check(
            16,
            "nothing-to-run: exit code is 0",
            ok=exit_code14 == 0,
            detail=f"got exit_code={exit_code14}",
        )

        # ==================================================================
        # FIXTURE: independence
        # ==================================================================

        exit_code_ind, report16 = _run_fixture("independence", tmp_dir=tmp)

        # ------------------------------------------------------------------
        # Check 17: both projects appear in the report (not vacuous: must
        # confirm each project actually ran at least one command)
        # ------------------------------------------------------------------
        proj_pass = _find_project(report16, "proj-pass") if report16 else None
        proj_fail = _find_project(report16, "proj-fail") if report16 else None
        pass_statuses = _project_stage_statuses(proj_pass) if proj_pass else {}
        fail_statuses = _project_stage_statuses(proj_fail) if proj_fail else {}
        both_ran = (
            proj_pass is not None
            and proj_fail is not None
            # Each project must have at least one stage that actually ran
            # (status != skipped due to nothing_to_run)
            and any(s not in ("skipped",) for s in pass_statuses.values())
            and any(s not in ("skipped",) for s in fail_statuses.values())
        )
        _check(
            17,
            "independence: both projects appear and ran commands",
            ok=both_ran,
            detail=(
                f"proj-pass statuses={pass_statuses} proj-fail statuses={fail_statuses}"
            ),
        )

        # ------------------------------------------------------------------
        # Check 18: proj-pass has tests='pass'
        # ------------------------------------------------------------------
        _check(
            18,
            "independence: proj-pass has tests='pass'",
            ok=pass_statuses.get("tests") == "pass",
            detail=f"tests={pass_statuses.get('tests')} all={pass_statuses}",
        )

        # ------------------------------------------------------------------
        # Check 19: proj-fail has tests='fail'
        # ------------------------------------------------------------------
        _check(
            19,
            "independence: proj-fail has tests='fail'",
            ok=fail_statuses.get("tests") == "fail",
            detail=f"tests={fail_statuses.get('tests')} all={fail_statuses}",
        )

        # ------------------------------------------------------------------
        # Check 20: proj-pass build='pass' (not contaminated by proj-fail)
        # ------------------------------------------------------------------
        _check(
            20,
            "independence: proj-pass build='pass' (not contaminated by proj-fail)",
            ok=pass_statuses.get("build") == "pass",
            detail=f"build={pass_statuses.get('build')}",
        )

        # ------------------------------------------------------------------
        # Check 21: overall exit code is 1 (one project fails)
        # ------------------------------------------------------------------
        _check(
            21,
            "independence: exit code is 1 (one project fails)",
            ok=exit_code_ind == 1,
            detail=f"got exit_code={exit_code_ind}",
        )

        # ==================================================================
        # Cross-cutting: report structure (using build-gate report)
        # ==================================================================

        # ------------------------------------------------------------------
        # Check 22: executed commands have numeric duration_s > 0
        # ------------------------------------------------------------------
        executed_cmds = [
            cmd
            for cmd in (_project_commands(report) if report else [])
            if cmd.get("command") is not None  # synthetic entries have command=None
        ]
        has_duration = bool(executed_cmds) and all(
            isinstance(cmd.get("duration_s"), (int, float))
            and cmd.get("duration_s", -1) >= 0
            for cmd in executed_cmds
        )
        _check(
            22,
            "executed commands have numeric duration_s >= 0",
            ok=has_duration,
            detail=f"executed_cmds count={len(executed_cmds)} "
            f"durations={[c.get('duration_s') for c in executed_cmds]}",
        )

        # ------------------------------------------------------------------
        # Check 23: executed commands have a relative, in-repo log_path
        # ------------------------------------------------------------------
        has_log_path = bool(executed_cmds) and all(
            cmd.get("log_path")
            and cmd.get("log_path") != "<external>"
            and not Path(cmd["log_path"]).is_absolute()
            for cmd in executed_cmds
        )
        _check(
            23,
            "executed commands all have a relative log_path (not <external>)",
            ok=has_log_path,
            detail=f"log_paths={[c.get('log_path') for c in executed_cmds]}",
        )

        # ------------------------------------------------------------------
        # Check 24: output_tail is a list in all entries
        # ------------------------------------------------------------------
        all_cmds_in_report: list[dict] = []
        if report:
            for proj in report.get("projects", []):
                all_cmds_in_report.extend(proj.get("commands", []))
        tail_is_list = (
            all(isinstance(cmd.get("output_tail"), list) for cmd in all_cmds_in_report)
            if all_cmds_in_report
            else False
        )
        _check(
            24,
            "output_tail is a list in every command entry",
            ok=tail_is_list,
            detail="a command had non-list output_tail",
        )

        # ------------------------------------------------------------------
        # Check 25: findings is null in all command entries (v1)
        # ------------------------------------------------------------------
        findings_null = (
            all(cmd.get("findings") is None for cmd in all_cmds_in_report)
            if all_cmds_in_report
            else False
        )
        _check(
            25,
            "findings is null in all command entries (v1)",
            ok=findings_null,
            detail="at least one command had non-null findings",
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    passed = sum(1 for _, label, _ in _results if label == _PASS)
    total = len(_results)
    print(
        f"{'All checks passed' if passed == total else 'Some checks FAILED'}: "
        f"{passed}/{total}"
    )
    return 0 if passed == total else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    sys.exit(run_checks())
