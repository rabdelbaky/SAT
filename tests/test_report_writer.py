"""Tests for the report writer, secret masking, and size caps.

Seams under test:
  - mask_secrets(text) -> str
  - cap_output_tail(lines, max_lines, max_line_len) -> list[str]
  - cap_findings(findings, max_count) -> (list, true_total: int)
  - make_relative_path(path, root) -> str   (forward slashes, relative)
  - build_report(projects_data, repo_root, tail_lines) -> dict
  - write_report(report, output_path, size_cap_bytes) -> None
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pre_llm_checks import (
    build_report,
    cap_findings,
    cap_output_tail,
    make_relative_path,
    mask_secrets,
    write_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROOT = Path("/repo")


def _minimal_project_data(
    *,
    path: str = "backend",
    language: str = "python",
    commands: list | None = None,
) -> dict:
    """Return the minimal project-data dict accepted by build_report."""
    return {
        "path": path,
        "language": language,
        "commands": commands or [],
    }


def _minimal_command(
    *,
    command: list | None = None,
    scripts: list | None = None,
    source: str = "package.json",
    status: str = "pass",
    duration_s: float = 1.0,
    output_tail: list | None = None,
    log_path: str | None = None,
    findings: list | None = None,
) -> dict:
    return {
        "command": command or ["pytest"],
        "scripts": scripts or ["test"],
        "source": source,
        "status": status,
        "duration_s": duration_s,
        "output_tail": output_tail or [],
        "log_path": log_path,
        "findings": findings,
    }


# ===========================================================================
# Cycle 1 — schema_version and summary fields
# ===========================================================================


def test_report_has_schema_version():
    report = build_report([], _ROOT, tail_lines=50)
    assert report.get("schema_version") == "1.0"


def test_report_summary_at_top():
    """summary must be the first key in the report dict (JSON objects are ordered in 3.7+)."""
    report = build_report([], _ROOT, tail_lines=50)
    keys = list(report.keys())
    assert keys[0] == "schema_version"
    assert "summary" in report


def test_report_summary_contains_status():
    report = build_report([], _ROOT, tail_lines=50)
    assert "status" in report["summary"]


def test_report_summary_contains_project_count():
    projects = [_minimal_project_data()]
    report = build_report(projects, _ROOT, tail_lines=50)
    assert report["summary"]["project_count"] == 1


def test_report_summary_zero_projects():
    report = build_report([], _ROOT, tail_lines=50)
    assert report["summary"]["project_count"] == 0


# ===========================================================================
# Cycle 2 — per-command fields
# ===========================================================================


def test_command_entry_has_required_fields():
    cmd = _minimal_command()
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    result_cmd = report["projects"][0]["commands"][0]
    for field in (
        "command",
        "scripts",
        "source",
        "status",
        "duration_s",
        "output_tail",
        "log_path",
        "findings",
    ):
        assert field in result_cmd, f"Missing field: {field!r}"


def test_command_findings_is_null_when_none():
    cmd = _minimal_command(findings=None)
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    assert report["projects"][0]["commands"][0]["findings"] is None


def test_command_status_preserved():
    cmd = _minimal_command(status="fail")
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    assert report["projects"][0]["commands"][0]["status"] == "fail"


def test_command_duration_preserved():
    cmd = _minimal_command(duration_s=3.14)
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    assert report["projects"][0]["commands"][0]["duration_s"] == pytest.approx(3.14)


# ===========================================================================
# Cycle 3 — secret masking
# ===========================================================================


def test_mask_secrets_masks_bearer_token():
    text = "Authorization: Bearer ghp_abc123SECRET456"
    result = mask_secrets(text)
    assert "ghp_abc123SECRET456" not in result
    assert "***" in result


def test_mask_secrets_masks_api_key_in_url():
    text = "https://api.example.com/data?api_key=supersecretkey&format=json"
    result = mask_secrets(text)
    assert "supersecretkey" not in result


def test_mask_secrets_masks_password_in_connection_string():
    text = "postgresql://user:mysecretpassword@localhost:5432/db"
    result = mask_secrets(text)
    assert "mysecretpassword" not in result


def test_mask_secrets_masks_token_env_var():
    text = "TOKEN=abc123verysecrettoken"
    result = mask_secrets(text)
    assert "abc123verysecrettoken" not in result


def test_mask_secrets_leaves_normal_text_untouched():
    text = "Build succeeded in 3.2s"
    assert mask_secrets(text) == text


def test_mask_secrets_masks_generic_secret_key():
    text = "secret_key=xyzSECRETvalue123"
    result = mask_secrets(text)
    assert "xyzSECRETvalue123" not in result


def test_mask_secrets_masks_aws_access_key():
    text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    result = mask_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in result


def test_mask_secrets_applied_to_output_tail_in_report():
    sensitive = "TOKEN=supersecretvalue999"
    cmd = _minimal_command(output_tail=[sensitive, "normal line"])
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    tail = report["projects"][0]["commands"][0]["output_tail"]
    assert all("supersecretvalue999" not in line for line in tail)


# ===========================================================================
# Cycle 4 — output_tail line count and line length caps
# ===========================================================================


def test_cap_output_tail_truncates_to_max_lines():
    lines = [f"line {i}" for i in range(100)]
    result = cap_output_tail(lines, max_lines=50, max_line_len=500)
    assert len(result) == 50


def test_cap_output_tail_keeps_last_n_lines():
    lines = [f"line {i}" for i in range(100)]
    result = cap_output_tail(lines, max_lines=5, max_line_len=500)
    assert result == [f"line {i}" for i in range(95, 100)]


def test_cap_output_tail_truncates_long_lines():
    lines = ["x" * 600]
    result = cap_output_tail(lines, max_lines=50, max_line_len=500)
    assert len(result[0]) <= 500


def test_cap_output_tail_short_lines_unchanged():
    lines = ["hello", "world"]
    result = cap_output_tail(lines, max_lines=50, max_line_len=500)
    assert result == ["hello", "world"]


def test_cap_output_tail_empty_list():
    assert cap_output_tail([], max_lines=50, max_line_len=500) == []


def test_build_report_applies_tail_lines_cap():
    lines = [f"line {i}" for i in range(200)]
    cmd = _minimal_command(output_tail=lines)
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    tail = report["projects"][0]["commands"][0]["output_tail"]
    assert len(tail) <= 50


# ===========================================================================
# Cycle 5 — findings cap: max 50, true total reported
# ===========================================================================


def test_cap_findings_returns_first_50():
    findings = [{"msg": f"issue {i}"} for i in range(80)]
    capped, total = cap_findings(findings, max_count=50)
    assert len(capped) == 50
    assert capped[0]["msg"] == "issue 0"


def test_cap_findings_total_is_true_count():
    findings = [{"msg": f"issue {i}"} for i in range(80)]
    _, total = cap_findings(findings, max_count=50)
    assert total == 80


def test_cap_findings_under_limit_unchanged():
    findings = [{"msg": f"issue {i}"} for i in range(10)]
    capped, total = cap_findings(findings, max_count=50)
    assert len(capped) == 10
    assert total == 10


def test_cap_findings_empty():
    capped, total = cap_findings([], max_count=50)
    assert capped == []
    assert total == 0


def test_report_command_findings_capped_and_total_recorded():
    findings = [
        {"file": "a.py", "line": i, "rule": "E1", "severity": "error", "message": "bad"}
        for i in range(80)
    ]
    cmd = _minimal_command(findings=findings)
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    result_cmd = report["projects"][0]["commands"][0]
    assert len(result_cmd["findings"]) == 50
    assert result_cmd["findings_total"] == 80


def test_report_command_findings_total_equals_count_when_under_limit():
    findings = [
        {"file": "a.py", "line": i, "rule": "E1", "severity": "error", "message": "bad"}
        for i in range(5)
    ]
    cmd = _minimal_command(findings=findings)
    project = _minimal_project_data(commands=[cmd])
    report = build_report([project], _ROOT, tail_lines=50)
    result_cmd = report["projects"][0]["commands"][0]
    assert result_cmd.get("findings_total") == 5


# ===========================================================================
# Cycle 6 — 200 KB report cap: trim tails, then truncated=true
# ===========================================================================


def _big_report(*, tail_lines_per_cmd: int = 50) -> dict:
    """Build a report that will exceed 200 KB when serialised."""
    # 20 commands each with 50 lines of 500 chars = 500 KB+
    cmds = [
        _minimal_command(output_tail=["x" * 500] * tail_lines_per_cmd)
        for _ in range(20)
    ]
    project = _minimal_project_data(commands=cmds)
    return build_report([project], _ROOT, tail_lines=tail_lines_per_cmd)


def test_write_report_sets_truncated_true_when_over_cap(tmp_path):
    report = _big_report()
    out = tmp_path / "report.json"
    write_report(report, out, size_cap_bytes=200_000)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data.get("truncated") is True


def test_write_report_result_under_cap_after_trim(tmp_path):
    report = _big_report()
    out = tmp_path / "report.json"
    write_report(report, out, size_cap_bytes=200_000)
    assert out.stat().st_size <= 200_000


def test_write_report_no_truncated_flag_when_small(tmp_path):
    report = build_report([], _ROOT, tail_lines=50)
    out = tmp_path / "report.json"
    write_report(report, out, size_cap_bytes=200_000)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "truncated" not in data or data["truncated"] is False


def test_write_report_trims_tails_before_truncating(tmp_path):
    """After trimming, tails in commands are shorter than the original."""
    report = _big_report(tail_lines_per_cmd=50)
    out = tmp_path / "report.json"
    write_report(report, out, size_cap_bytes=200_000)
    data = json.loads(out.read_text(encoding="utf-8"))
    # At least some tails were trimmed (they can't all still be 50 lines of 500 chars)
    all_tails = [cmd["output_tail"] for cmd in data["projects"][0]["commands"]]
    total_tail_chars = sum(sum(len(l) for l in t) for t in all_tails)
    # Original: 20 cmds * 50 lines * 500 chars = 500,000 chars — must be less now
    assert total_tail_chars < 500_000


# ===========================================================================
# Cycle 7 — paths: relative to repo root, always forward slashes
# ===========================================================================


def test_make_relative_path_returns_forward_slashes():
    root = Path("/repo/root")
    path = Path("/repo/root/backend/src/app.py")
    result = make_relative_path(path, root)
    assert "\\" not in result
    assert result == "backend/src/app.py"


def test_make_relative_path_already_relative():
    root = Path("/repo")
    path = Path("/repo/a/b/c.py")
    assert make_relative_path(path, root) == "a/b/c.py"


def test_make_relative_path_root_itself():
    root = Path("/repo")
    result = make_relative_path(Path("/repo"), root)
    assert result == "."


def test_make_relative_path_string_input():
    root = Path("/repo")
    result = make_relative_path("/repo/sub/file.py", root)
    assert result == "sub/file.py"
    assert "\\" not in result


def test_report_paths_use_forward_slashes_on_any_platform(tmp_path):
    log = tmp_path / "sub" / "log.txt"
    cmd = _minimal_command(log_path=str(log), source=str(tmp_path / "package.json"))
    project = _minimal_project_data(path=str(tmp_path / "sub"), commands=[cmd])
    report = build_report([project], tmp_path, tail_lines=50)
    result_cmd = report["projects"][0]["commands"][0]
    if result_cmd["log_path"] is not None:
        assert "\\" not in result_cmd["log_path"]


# ===========================================================================
# Cycle 8 — always written, even on crash (summary.status = "error")
# ===========================================================================


def test_write_report_creates_file(tmp_path):
    report = build_report([], _ROOT, tail_lines=50)
    out = tmp_path / "pre-llm-report.json"
    write_report(report, out, size_cap_bytes=200_000)
    assert out.exists()


def test_write_report_valid_json(tmp_path):
    report = build_report([], _ROOT, tail_lines=50)
    out = tmp_path / "pre-llm-report.json"
    write_report(report, out, size_cap_bytes=200_000)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_build_report_error_status():
    """build_report can be called with status='error' for crash reports."""
    report = build_report([], _ROOT, tail_lines=50, status="error")
    assert report["summary"]["status"] == "error"


def test_write_report_overwrites_existing_file(tmp_path):
    out = tmp_path / "report.json"
    out.write_text('{"old": true}', encoding="utf-8")
    report = build_report([], _ROOT, tail_lines=50)
    write_report(report, out, size_cap_bytes=200_000)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "schema_version" in data
