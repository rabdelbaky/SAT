"""In-process tests of pre_llm_checks.main(): masking, report, .gitignore, warnings.

Seam: main(argv) -> exit code, plus what it prints (capsys), the report file
it writes (--output) and the files it leaves in the temp repo.

Every real run uses a temp Python project whose only command is a
pre-llm.toml ``tests`` override running this interpreter, so no toolchain
is needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import runner
from detection import DetectionResult, detect_commands
from discovery import discover_projects
from orchestrator import (
    OrchestratorOptions,
    ProjectResult,
    project_results_to_report_data,
    run_project,
)
from pre_llm_checks import build_report, load_languages, main

FIXTURES = Path(__file__).parent / "fixtures"
LANGUAGES = load_languages()
TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _py(code: str) -> str:
    """An override command that runs *code* with this interpreter."""
    return f'"{sys.executable}" -c "{code}"'


def _python_project(root: Path, tests_cmd: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "pre-llm.toml").write_text(
        f"[[project]]\npath = \".\"\ntests = '''{tests_cmd}'''\n", encoding="utf-8"
    )
    return root


def _run(tmp_path: Path, root: Path, *extra: str) -> tuple[int, dict | None]:
    out = tmp_path / "report.json"
    code = main(["--path", str(root), "--output", str(out), *extra])
    report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return code, report


# ---------------------------------------------------------------------------
# 1. Logs and report never contain secrets
# ---------------------------------------------------------------------------


def test_runner_mask_uses_pattern_masking():
    """The circular-import fallback is gone: runner masks by pattern."""
    assert runner._mask("password=hunter2xyz", []) == "password=***"


def test_secrets_masked_in_log_file_and_report(tmp_path):
    root = _python_project(
        tmp_path / "repo",
        _py("print('password=hunter2xyz'); print('postgres://u:s3cret@h/db')"),
    )
    code, report = _run(tmp_path, root)
    assert code == 0

    logs = list((root / ".pre-llm" / "logs").rglob("*.log"))
    assert logs, "no log file written"
    log_text = "".join(p.read_text(encoding="utf-8") for p in logs)
    assert "password=***" in log_text  # the output really was logged
    report_text = json.dumps(report)
    for secret in ("hunter2xyz", "s3cret"):
        assert secret not in log_text
        assert secret not in report_text


# ---------------------------------------------------------------------------
# 2. Commands are masked where shown; the real command is unchanged
# ---------------------------------------------------------------------------


def _token_project(tmp_path: Path) -> Path:
    # Prints the length of the argument it really received, then fails so the
    # command shows on the Details line.
    code = "import sys; print('argv1', len(sys.argv[1])); sys.exit(1)"
    return _python_project(tmp_path / "repo", f"{_py(code)} --token={TOKEN}")


def test_command_masked_in_report_and_terminal(tmp_path, capsys):
    root = _token_project(tmp_path)
    code, report = _run(tmp_path, root, "--verbose")
    assert code == 1
    stdout = capsys.readouterr().out

    assert TOKEN not in stdout
    details = stdout.split("Details:", 1)[1]
    assert "--token=***" in details
    commands = stdout.split("Commands:", 1)[1].split("Details:", 1)[0]
    assert "--token=***" in commands

    tests_cmds = [c for c in report["projects"][0]["commands"] if c["stage"] == "tests"]
    assert tests_cmds[0]["command"][-1] == "--token=***"
    assert TOKEN not in json.dumps(report)
    # The command that ran got the real token: len("--token=" + TOKEN) == 48.
    assert "argv1 48" in tests_cmds[0]["output_tail"]


def test_command_masked_in_dry_run(tmp_path, capsys):
    root = _token_project(tmp_path)
    code, _ = _run(tmp_path, root, "--dry-run")
    assert code == 0
    stdout = capsys.readouterr().out
    assert "--token=***" in stdout
    assert TOKEN not in stdout


# ---------------------------------------------------------------------------
# 3. A report is written on every early exit
# ---------------------------------------------------------------------------


def _bad_path(tmp_path, monkeypatch):
    return ["--path", str(tmp_path / "missing")]


def _bad_languages(tmp_path, monkeypatch):
    monkeypatch.setenv("PRE_LLM_LANGUAGES_TOML", str(tmp_path / "nope.toml"))
    return ["--path", str(tmp_path)]


def _bad_pre_llm(tmp_path, monkeypatch):
    (tmp_path / "pre-llm.toml").write_text("bogus = 1\n", encoding="utf-8")
    return ["--path", str(tmp_path)]


def _bad_steps(tmp_path, monkeypatch):
    return ["--path", str(tmp_path), "--steps", "build,bogus"]


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize(
    "make_args", [_bad_path, _bad_languages, _bad_pre_llm, _bad_steps]
)
def test_error_exit_writes_error_report(tmp_path, monkeypatch, capsys, make_args, dry_run):
    out = tmp_path / "out" / "report.json"
    argv = make_args(tmp_path, monkeypatch) + ["--output", str(out)]
    if dry_run:
        argv.append("--dry-run")
    assert main(argv) == 2
    assert "ERROR:" in capsys.readouterr().err

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["status"] == "error"
    assert report["projects"] == []
    assert report["warnings"] == []


@pytest.mark.parametrize("dry_run", [False, True])
def test_no_project_writes_no_project_report(tmp_path, capsys, dry_run):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "report.json"
    argv = ["--path", str(repo), "--output", str(out)] + (["--dry-run"] if dry_run else [])
    assert main(argv) == 3
    assert "No supported projects found." in capsys.readouterr().err

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["status"] == "no_project"
    assert report["projects"] == []


# ---------------------------------------------------------------------------
# 4. --add-gitignore
# ---------------------------------------------------------------------------


def _passing_project(tmp_path: Path) -> Path:
    return _python_project(tmp_path / "repo", _py("pass"))


def test_add_gitignore_creates_missing_file(tmp_path):
    root = _passing_project(tmp_path)
    code, _ = _run(tmp_path, root, "--add-gitignore")
    assert code == 0
    assert (root / ".gitignore").read_bytes() == b".pre-llm/\n"


@pytest.mark.parametrize(
    "before, after",
    [
        (b"node_modules", b"node_modules\n.pre-llm/\n"),
        (b"node_modules\n", b"node_modules\n.pre-llm/\n"),
        (b"# keep\r\ndist/\r\n", b"# keep\r\ndist/\r\n.pre-llm/\n"),
    ],
)
def test_add_gitignore_appends_and_keeps_content(tmp_path, before, after):
    root = _passing_project(tmp_path)
    (root / ".gitignore").write_bytes(before)
    _run(tmp_path, root, "--add-gitignore")
    assert (root / ".gitignore").read_bytes() == after


def test_gitignore_not_touched_without_flag(tmp_path):
    root = _passing_project(tmp_path)
    (root / ".gitignore").write_bytes(b"node_modules\n")
    _run(tmp_path, root)
    assert (root / ".gitignore").read_bytes() == b"node_modules\n"

    missing = _python_project(tmp_path / "repo2", _py("pass"))
    _run(tmp_path, missing)
    assert not (missing / ".gitignore").exists()


@pytest.mark.parametrize("listed", [b".pre-llm\n", b".pre-llm/\n", b"/.pre-llm/\n"])
def test_add_gitignore_leaves_file_when_already_listed(tmp_path, listed):
    root = _passing_project(tmp_path)
    (root / ".gitignore").write_bytes(listed)
    _run(tmp_path, root, "--add-gitignore")
    assert (root / ".gitignore").read_bytes() == listed


# ---------------------------------------------------------------------------
# 5. gitignore_missing warning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gitignore", [None, b"node_modules\n"])
def test_gitignore_missing_warning(tmp_path, capsys, gitignore):
    root = _passing_project(tmp_path)
    if gitignore is not None:
        (root / ".gitignore").write_bytes(gitignore)
    code, report = _run(tmp_path, root)
    assert code == 0  # a warning never changes the exit code
    captured = capsys.readouterr()
    assert "WARNING:" in captured.err and ".gitignore" in captured.err
    assert report["warnings"] == ["gitignore_missing"]
    assert "Warnings:" in captured.out
    assert "  (repo): gitignore_missing\n" in captured.out


def test_no_gitignore_warning_when_covered_or_added(tmp_path, capsys):
    root = _passing_project(tmp_path)
    (root / ".gitignore").write_bytes(b".pre-llm/\n")
    _, report = _run(tmp_path, root)
    assert report["warnings"] == []

    other = _python_project(tmp_path / "repo2", _py("pass"))
    _, report = _run(tmp_path, other, "--add-gitignore")
    assert report["warnings"] == []
    assert "gitignore_missing" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 6. build_files and skipped_scripts per project
# ---------------------------------------------------------------------------


def _report_project(results: list[ProjectResult], repo_root: Path) -> dict:
    data = project_results_to_report_data(results, repo_root)
    return build_report(data, repo_root, 50)["projects"][0]


def test_report_lists_build_files_and_skipped_scripts_risky(tmp_path):
    root = FIXTURES / "risky-scripts"
    (project,) = discover_projects(root, LANGUAGES)
    detected = detect_commands(project, LANGUAGES["javascript"])
    # No commands: run_project returns at once (nothing_to_run), runs nothing.
    result = run_project(
        project=project,
        lang_cfg=LANGUAGES["javascript"],
        detection=DetectionResult(commands={}, skipped_scripts=detected.skipped_scripts),
        opts=OrchestratorOptions(),
        log_dir=tmp_path / "logs",
        repo_root=root,
    )
    entry = _report_project([result], root)

    assert entry["build_files"] == ["package.json"]
    names = {s["name"] for s in entry["skipped_scripts"]}
    assert names == {"lint:fix", "check", "test:watch", "dev", "format"}
    for s in entry["skipped_scripts"]:
        assert set(s) == {"name", "reason"} and s["reason"]


def test_report_lists_build_files_monorepo_ml():
    root = FIXTURES / "monorepo"
    ml = next(
        p for p in discover_projects(root, LANGUAGES)
        if p.path.resolve() == (root / "services" / "ml").resolve()
    )
    entry = _report_project([ProjectResult(project=ml)], root)
    assert entry["build_files"] == [
        "services/ml/pyproject.toml",
        "services/ml/requirements.txt",
    ]
    assert entry["skipped_scripts"] == []


# ---------------------------------------------------------------------------
# 7. no_project / unsupported_extension reach the report and terminal
# ---------------------------------------------------------------------------


def test_discovery_warnings_in_report_and_terminal(tmp_path, capsys):
    root = _passing_project(tmp_path)
    (root / ".gitignore").write_bytes(b".pre-llm/\n")
    (root / "tools").mkdir()
    (root / "tools" / "x.js").write_text("", encoding="utf-8")
    (root / "tools" / "y.lua").write_text("", encoding="utf-8")
    code, report = _run(tmp_path, root)
    assert code == 0
    assert report["warnings"] == [
        "no_project: tools",
        "unsupported_extension: tools",
    ]
    out = capsys.readouterr().out
    assert "  tools: no_project\n" in out
    assert "  tools: unsupported_extension\n" in out


# ---------------------------------------------------------------------------
# 9. pre-llm.toml type errors: ERROR and exit 2, never a traceback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dry_run", [False, True])
def test_pre_llm_toml_type_error_exits_2(tmp_path, capsys, dry_run):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (root / "pre-llm.toml").write_text(
        '[[project]]\npath = "a"\ntests = 5\n', encoding="utf-8"
    )
    code, _ = _run(tmp_path, root, *(["--dry-run"] if dry_run else []))
    err = capsys.readouterr().err
    assert code == 2
    assert 'ERROR: pre-llm.toml: [[project]] "a": tests must be a string' in err
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# 11. --dry-run project paths are relative, forward slashes
# ---------------------------------------------------------------------------


def test_dry_run_paths_relative_to_root(tmp_path, capsys):
    code, _ = _run(tmp_path, FIXTURES / "monorepo", "--dry-run")
    assert code == 0
    headers = [
        line.split("  ", 1)[0]
        for line in capsys.readouterr().out.splitlines()
        if line.strip() and not line.startswith(" ")
    ]
    assert headers == [".", "packages/api", "packages/ui", "services/ml", "services/worker"]
