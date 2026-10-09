"""Manual smoke-checks for the report writer, secret masking, and size caps.

Run:  python tests/manual_report_check.py
      python tests/manual_report_check.py --keep

Each check prints "PASS <name>" or "FAIL <name>: <reason>".

With --keep the main sample report is written to ./sample-report.json (current
working directory) instead of a temp folder, kept after the run, and its path
is printed at the end.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
from pathlib import Path

# Ensure the repo root is on the path regardless of where this is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pre_llm_checks import build_report, write_report  # noqa: E402

# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(tempfile.mkdtemp())  # stable fake root for this run


def _pass(name: str) -> None:
    print(f"PASS {name}")


def _fail(name: str, reason: str) -> None:
    print(f"FAIL {name}: {reason}")


def _cmd(
    *,
    output_tail: list[str] | None = None,
    findings: list | None = None,
    log_path: str | None = None,
    status: str = "pass",
    duration_s: float = 0.1,
) -> dict:
    return {
        "command": ["pytest"],
        "scripts": ["test"],
        "source": "pyproject.toml",
        "status": status,
        "duration_s": duration_s,
        "output_tail": output_tail or [],
        "log_path": log_path,
        "findings": findings,
    }


def _project(commands: list[dict], *, path: str = "backend") -> dict:
    return {"path": path, "language": "python", "commands": commands}


def _write(report: dict, tmp: Path, *, size_cap: int = 200_000) -> Path:
    out = tmp / "pre-llm-report.json"
    write_report(report, out, size_cap_bytes=size_cap)
    return out


@contextlib.contextmanager
def _output_dir(keep: bool):
    """Yield the directory to use for the main sample report.

    With *keep=True* yields Path('.') and never cleans up.
    With *keep=False* yields a temporary directory that is deleted on exit.
    """
    if keep:
        yield Path(".")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)


# ---------------------------------------------------------------------------
# Check 1 — file written and valid JSON
# ---------------------------------------------------------------------------


def check_1_file_written_and_valid_json(sample_dir: Path | None = None) -> None:
    name = "1_file_written_valid_json"

    def _run(out_dir: Path) -> str | None:
        """Return failure reason or None on success."""
        out = _write(build_report([], _REPO_ROOT, tail_lines=50), out_dir)
        if not out.exists():
            return "output file does not exist"
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return f"invalid JSON: {exc}"
        if not isinstance(data, dict):
            return f"top level is {type(data).__name__}, expected dict"
        return None

    if sample_dir is not None:
        reason = _run(sample_dir)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            reason = _run(Path(tmp))

    if reason:
        _fail(name, reason)
    else:
        _pass(name)


# ---------------------------------------------------------------------------
# Check 2 — schema_version, summary at top, findings null, environment block
# ---------------------------------------------------------------------------


def check_2_schema_summary_findings_environment() -> None:
    name = "2_schema_summary_findings_environment"
    # Pass a fake environment block through; build_report stores whatever
    # extra keys are given at the top level via the caller adding them after.
    report = build_report(
        [_project([_cmd(findings=None)])],
        _REPO_ROOT,
        tail_lines=50,
    )
    # Attach a fake environment block (populated by the runner in a later session).
    report["environment"] = {"os": "linux", "python": "3.11.0"}

    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp))
        data = json.loads(out.read_text(encoding="utf-8"))

    keys = list(data.keys())
    # schema_version must be first
    if keys[0] != "schema_version":
        _fail(name, f"first key is {keys[0]!r}, expected 'schema_version'")
        return
    if data.get("schema_version") != "1.0":
        _fail(name, f"schema_version={data.get('schema_version')!r}, expected '1.0'")
        return
    # summary must be present (second key)
    if "summary" not in data:
        _fail(name, "key 'summary' missing")
        return
    # findings must be null for a command that had none
    cmd_entry = data["projects"][0]["commands"][0]
    if cmd_entry.get("findings") is not None:
        _fail(name, f"findings={cmd_entry['findings']!r}, expected null")
        return
    # environment block must be present
    if "environment" not in data:
        _fail(name, "key 'environment' missing")
        return
    _pass(name)


# ---------------------------------------------------------------------------
# Check 3 — secrets masked in output_tail
# ---------------------------------------------------------------------------

_SECRET_LINES = [
    "Authorization: Bearer ghp_FAKETOKEN1234567890abcdef",
    "api_key=supersecretapikey99",
    "password=hunter2",
    "postgresql://admin:s3cr3tP@ss@db.internal:5432/prod",
]
_SECRET_VALUES = [
    "ghp_FAKETOKEN1234567890abcdef",
    "supersecretapikey99",
    "hunter2",
    "s3cr3tP@ss",
]


def check_3_secrets_masked() -> None:
    name = "3_secrets_masked"
    report = build_report(
        [_project([_cmd(output_tail=_SECRET_LINES)])],
        _REPO_ROOT,
        tail_lines=50,
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp))
        raw = out.read_text(encoding="utf-8")

    for secret in _SECRET_VALUES:
        if secret in raw:
            _fail(name, f"secret {secret!r} found in report file")
            return
    _pass(name)


# ---------------------------------------------------------------------------
# Check 4 — output_tail capped at 50 lines
# ---------------------------------------------------------------------------


def check_4_output_tail_50_lines() -> None:
    name = "4_output_tail_50_lines"
    lines = [f"line {i}" for i in range(200)]
    report = build_report(
        [_project([_cmd(output_tail=lines)])],
        _REPO_ROOT,
        tail_lines=50,
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp))
        data = json.loads(out.read_text(encoding="utf-8"))

    tail = data["projects"][0]["commands"][0]["output_tail"]
    if len(tail) != 50:
        _fail(name, f"tail has {len(tail)} lines, expected 50")
        return
    # Must be the last 50 lines
    expected_last = f"line {199}"
    if tail[-1] != expected_last:
        _fail(name, f"last tail line is {tail[-1]!r}, expected {expected_last!r}")
        return
    _pass(name)


# ---------------------------------------------------------------------------
# Check 5 — 600-char line cut to 500
# ---------------------------------------------------------------------------


def check_5_long_line_truncated() -> None:
    name = "5_long_line_truncated_to_500"
    long_line = "x" * 600
    report = build_report(
        [_project([_cmd(output_tail=[long_line])])],
        _REPO_ROOT,
        tail_lines=50,
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp))
        data = json.loads(out.read_text(encoding="utf-8"))

    tail = data["projects"][0]["commands"][0]["output_tail"]
    if not tail:
        _fail(name, "output_tail is empty")
        return
    actual_len = len(tail[0])
    if actual_len != 500:
        _fail(name, f"line length is {actual_len}, expected 500")
        return
    _pass(name)


# ---------------------------------------------------------------------------
# Check 6 — 80 findings → 50 kept, findings_total = 80
# ---------------------------------------------------------------------------


def check_6_findings_cap_and_total() -> None:
    name = "6_findings_80_capped_to_50_total_80"
    findings = [
        {"file": "a.py", "line": i, "rule": "E1", "severity": "error", "message": "bad"}
        for i in range(80)
    ]
    report = build_report(
        [_project([_cmd(findings=findings)])],
        _REPO_ROOT,
        tail_lines=50,
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp))
        data = json.loads(out.read_text(encoding="utf-8"))

    cmd_entry = data["projects"][0]["commands"][0]
    kept = cmd_entry.get("findings", [])
    total = cmd_entry.get("findings_total")

    if len(kept) != 50:
        _fail(name, f"findings has {len(kept)} entries, expected 50")
        return
    if total != 80:
        _fail(name, f"findings_total={total!r}, expected 80")
        return
    _pass(name)


# ---------------------------------------------------------------------------
# Check 7 — oversized report trimmed and truncated=true
# ---------------------------------------------------------------------------


def check_7_oversized_report_trimmed_truncated() -> None:
    name = "7_oversized_report_trimmed_truncated"
    # 20 commands × 50 lines × 500 chars ≈ 500 KB serialised — well over 200 KB.
    # build_report applies cap_output_tail (50 lines, 500 chars) so the data
    # arrives at write_report already at maximum density; it is still ~500 KB.
    cmds = [_cmd(output_tail=["x" * 500] * 50) for _ in range(20)]
    report = build_report([_project(cmds)], _REPO_ROOT, tail_lines=50)

    import json as _json

    raw_size = len(_json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    if raw_size <= 200_000:
        _fail(
            name, f"fake data only {raw_size} bytes — not large enough to trigger trim"
        )
        return

    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp), size_cap=200_000)
        size = out.stat().st_size
        data = json.loads(out.read_text(encoding="utf-8"))

    if size > 200_000:
        _fail(name, f"file is {size} bytes, exceeds 200 000 byte cap")
        return
    if data.get("truncated") is not True:
        _fail(name, f"truncated={data.get('truncated')!r}, expected true")
        return
    _pass(name)


# ---------------------------------------------------------------------------
# Check 8 — crash path: summary.status = "error"
# ---------------------------------------------------------------------------


def check_8_crash_writes_error_status() -> None:
    name = "8_crash_writes_error_status"
    # Simulate what the orchestrator does on an unexpected exception:
    # build a report with status="error" and write it.
    report = build_report([], _REPO_ROOT, tail_lines=50, status="error")

    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp))
        if not out.exists():
            _fail(name, "report file not written after simulated crash")
            return
        data = json.loads(out.read_text(encoding="utf-8"))

    actual = data.get("summary", {}).get("status")
    if actual != "error":
        _fail(name, f"summary.status={actual!r}, expected 'error'")
        return
    _pass(name)


# ---------------------------------------------------------------------------
# Check 9 — all paths use forward slashes and are relative
# ---------------------------------------------------------------------------


def check_9_paths_forward_slashes_relative() -> None:
    name = "9_paths_forward_slashes_relative"
    repo_root = _REPO_ROOT
    project_dir = repo_root / "backend"
    log_file = project_dir / "logs" / "build.log"
    source_file = project_dir / "pyproject.toml"

    cmd = {
        "command": ["python", "-m", "build"],
        "scripts": ["build"],
        "source": str(source_file),
        "status": "pass",
        "duration_s": 1.2,
        "output_tail": [],
        "log_path": str(log_file),
        "findings": None,
    }
    report = build_report(
        [{"path": str(project_dir), "language": "python", "commands": [cmd]}],
        repo_root,
        tail_lines=50,
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = _write(report, Path(tmp))
        raw = out.read_text(encoding="utf-8")

    # No Windows-style backslashes anywhere in the report text
    if "\\" in raw:
        idx = raw.index("\\")
        snippet = raw[max(0, idx - 30) : idx + 30]
        _fail(name, f"backslash found near: ...{snippet}...")
        return

    data = json.loads(raw)
    cmd_entry = data["projects"][0]["commands"][0]

    # project path must be relative
    proj_path = data["projects"][0]["path"]
    if proj_path is None:
        _fail(name, "project path is null")
        return
    if Path(proj_path).is_absolute():
        _fail(name, f"project path {proj_path!r} is absolute, expected relative")
        return

    # log_path must be relative
    log_path = cmd_entry.get("log_path")
    if log_path is None:
        _fail(name, "log_path is null, expected a relative forward-slash path")
        return
    if Path(log_path).is_absolute():
        _fail(name, f"log_path {log_path!r} is absolute, expected relative")
        return

    # source must be relative
    source = cmd_entry.get("source")
    if source is None:
        _fail(name, "source is null, expected a relative forward-slash path")
        return
    if Path(source).is_absolute():
        _fail(name, f"source {source!r} is absolute, expected relative")
        return

    _pass(name)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_CHECKS = [
    check_1_file_written_and_valid_json,
    check_2_schema_summary_findings_environment,
    check_3_secrets_masked,
    check_4_output_tail_50_lines,
    check_5_long_line_truncated,
    check_6_findings_cap_and_total,
    check_7_oversized_report_trimmed_truncated,
    check_8_crash_writes_error_status,
    check_9_paths_forward_slashes_relative,
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Manual smoke-checks for the report writer."
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help=(
            "Write the main sample report to ./sample-report.json and keep it "
            "after the run."
        ),
    )
    args = parser.parse_args()

    sample_path: Path | None = None

    with _output_dir(args.keep) as main_dir:
        for check in _CHECKS:
            try:
                if check is check_1_file_written_and_valid_json:
                    check(sample_dir=main_dir)
                    if args.keep:
                        sample_path = main_dir / "pre-llm-report.json"
                else:
                    check()
            except Exception as exc:  # noqa: BLE001
                name = check.__name__.split("check_", 1)[-1]
                _fail(name, f"unexpected exception: {exc}")

    if args.keep and sample_path is not None:
        print(f"sample report: {sample_path.resolve()}")
