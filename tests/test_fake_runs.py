"""Fake-tool runs with golden files: every language, no real tools (Session 21).

Seam: pre_llm_checks.main(argv) with orchestrator.run_command replaced by a
fake that returns a runner.CommandResult, and pre_llm_checks.probe_version
replaced by a stub, so planning and status logic is tested for every
language on any machine (Rust, PHP, Swift and C/C++ included).
subprocess.Popen is patched to raise, so nothing real can start.

For each fixture (a copy in tmp_path, never tests/fixtures itself):
  plan     --dry-run stdout
  ok       every command passes   (exit 0, output "fake ok")
  fail     every command fails    (exit 1, output "fake failure")
  missing  every tool is missing  (tool_not_installed)

The text block is compared with tests/golden/<fixture>.txt.  Refresh with
UPDATE_GOLDEN=1 (see golden_files.py), review the diff, commit.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import orchestrator
import pre_llm_checks
from golden_files import GOLDEN_DIR, check_golden
from runner import CommandResult

FIXTURES = Path(__file__).parent / "fixtures"

_GENERATED = "cpp-generated"  # no fixture folder: built in tmp_path below
_FIXTURE_NAMES = [
    "python-ok",
    "python-cov-addopts",
    "js-ok",
    "ts-ok",
    "java-maven-ok",
    "java-gradle-ok",
    "kotlin-gradle-ok",
    "go-ok",
    "go-golangci-ok",
    "csharp-ok",
    "rust-ok",
    "php-ok",
    "php-unit-ok",
    "ruby-ok",
    "ruby-rspec-ok",
    "swift-ok",
    _GENERATED,
]
# Written out, not len(_FIXTURE_NAMES): a list that silently shrinks must fail.
_EXPECTED_FIXTURE_COUNT = 17

# Dependency folders a real machine would have after installing packages.
# Without them every stage is skipped as dependencies_missing before any
# command runs, so the fake would never be called.
_INSTALLED_DEPS = {"php-unit-ok": ["vendor"]}

# Local build output and installed packages are not part of a fixture;
# leaving them out keeps the copy the same on every machine.
_COPY_IGNORE = shutil.ignore_patterns(
    ".pre-llm", "node_modules", "vendor", "target", "build", ".build", "bin",
    "obj", "out", ".gradle", ".venv", "venv", "__pycache__",
)

_SCENARIOS = {
    "ok": CommandResult(
        status="pass", exit_code=0, duration_s=0.0,
        output="fake ok\n", output_tail=["fake ok"],
    ),
    "fail": CommandResult(
        status="fail", exit_code=1, duration_s=0.0,
        output="fake failure\n", output_tail=["fake failure"],
    ),
    "missing": CommandResult(
        status="tool_not_installed", exit_code=None, duration_s=0.0,
        output="", output_tail=[],
    ),
}

_STAGE_LINE = re.compile(r"^  (build|lint|tests|coverage): ")

_RAN: set[str] = set()
_STARTED: list = []  # every attempt to start a real process

# platform caches uname(); fill the cache now, because on Windows with
# Python 3.11 the first call may run "ver", which the Popen guard forbids.
platform.uname()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_process(*args, **kwargs):
    # Recorded as well as raised: main() catches exceptions, so the raise
    # alone could be swallowed.
    _STARTED.append(args[0] if args else kwargs.get("args"))
    raise AssertionError(f"a real process was started: {args[0] if args else kwargs}")


def _install_fakes(monkeypatch, result: CommandResult) -> None:
    """Every command returns *result*; nothing real can run."""

    def fake_run_command(*args, **kwargs) -> CommandResult:
        # Fresh lists so the orchestrator can never change the shared result.
        return CommandResult(
            status=result.status,
            exit_code=result.exit_code,
            duration_s=result.duration_s,
            output=result.output,
            output_tail=list(result.output_tail),
        )

    monkeypatch.setattr(orchestrator, "run_command", fake_run_command)
    monkeypatch.setattr(pre_llm_checks, "probe_version", lambda exe, cwd: None)
    monkeypatch.setattr(subprocess, "Popen", _no_process)


def _make_copy(name: str, dest: Path) -> Path:
    """Copy fixture *name* (or build cpp-generated) into *dest*; return it."""
    if name == _GENERATED:
        dest.mkdir(parents=True)
        (dest / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.10)\n"
            "project(demo CXX)\n"
            "add_executable(demo main.cpp)\n",
            encoding="utf-8",
        )
        (dest / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    else:
        shutil.copytree(FIXTURES / name, dest, ignore=_COPY_IGNORE)
    for folder in _INSTALLED_DEPS.get(name, []):
        (dest / folder).mkdir(exist_ok=True)
    return dest


def _table_cells(stdout: str) -> list[str]:
    """One "<project> <build> <lint> <tests> <coverage>" string per table row."""
    lines = stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("Project")), None)
    if start is None:  # no table printed (e.g. an internal error)
        return []
    rows = []
    for line in lines[start + 2:]:  # skip header and dashes
        if not line.strip():
            break
        cols = re.split(r"\s{2,}", line.strip())
        rows.append(" ".join([cols[0], *cols[-4:]]))
    return rows


def _normalise(text: str, tmp_path: Path) -> str:
    text = text.replace("\\", "/")
    for tmp in sorted(
        {tmp_path.as_posix(), tmp_path.resolve().as_posix()}, key=len, reverse=True
    ):
        text = text.replace(tmp, "<tmp>")
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def _block(name: str, tmp_path: Path, monkeypatch, capsys) -> tuple[str, dict]:
    """Run all scenarios for *name*; return (text block, parsed sections)."""
    report = tmp_path / "report.json"
    parsed: dict = {}

    _install_fakes(monkeypatch, _SCENARIOS["ok"])
    root = _make_copy(name, tmp_path / "plan" / name)
    code = pre_llm_checks.main(["--path", str(root), "--output", str(report), "--dry-run"])
    assert code == 0, capsys.readouterr().err
    plan = capsys.readouterr().out.splitlines()
    parsed["plan"] = plan
    out = [f"# {name}", "## plan", *plan]

    for scenario, result in _SCENARIOS.items():
        _install_fakes(monkeypatch, result)
        root = _make_copy(name, tmp_path / scenario / name)
        code = pre_llm_checks.main(["--path", str(root), "--output", str(report)])
        captured = capsys.readouterr()
        rows = _table_cells(captured.out)
        parsed[scenario] = (rows, code)
        out += [f"## {scenario}", *(f"cells: {r}" for r in rows), f"exit: {code}"]

    return _normalise("\n".join(out), tmp_path), parsed


def _cells_only(rows: list[str]) -> list[str]:
    """The four stage cells of every row (project name dropped)."""
    return [c for r in rows for c in r.split(" ")[1:]]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fixture_list_is_complete():
    assert len(_FIXTURE_NAMES) == _EXPECTED_FIXTURE_COUNT
    assert len(set(_FIXTURE_NAMES)) == _EXPECTED_FIXTURE_COUNT
    for name in _FIXTURE_NAMES:
        if name != _GENERATED:
            assert (FIXTURES / name).is_dir(), f"fixture missing: {name}"


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_fake_run_matches_golden(name, tmp_path, monkeypatch, capsys):
    _STARTED.clear()
    text, parsed = _block(name, tmp_path, monkeypatch, capsys)
    assert _STARTED == [], f"{name}: real processes started: {_STARTED}"

    # Guards against a vacuous pass (checked on every run, also when updating).
    assert any(_STAGE_LINE.match(line) for line in parsed["plan"]), (
        f"{name}: --dry-run planned no stage command"
    )
    fail_rows, fail_code = parsed["fail"]
    assert "FAIL" in _cells_only(fail_rows), f"{name}: fail scenario has no FAIL cell"
    assert fail_code == 1, f"{name}: fail scenario exit {fail_code}, expected 1"
    missing_cells = _cells_only(parsed["missing"][0])
    assert not any(c == "PASS" or c.endswith("%") for c in missing_cells), (
        f"{name}: missing scenario has a PASS cell"
    )

    check_golden(
        GOLDEN_DIR / f"{name}.txt",
        text,
        f"{name}: fake-run output differs from tests/golden/{name}.txt",
    )
    _RAN.add(name)


def test_every_fixture_ran():
    """Last in the file: every parametrised case above ran and passed."""
    assert _RAN == set(_FIXTURE_NAMES), (
        f"not run or failed: {sorted(set(_FIXTURE_NAMES) - _RAN)}"
    )
    assert len(_RAN) == _EXPECTED_FIXTURE_COUNT
