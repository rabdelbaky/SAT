"""Tests for Rust detection (Session 16).

cargo build / clippy / test are toolchain built-ins.  Coverage is NOT built-in:
`cargo tarpaulin` is a separate install, so running it on every project failed
projects that never declared it.  It runs only when the project declares it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project
from pre_llm_checks import load_languages

_RUST = load_languages()["rust"]

_CARGO = '[package]\nname = "x"\nversion = "0.1.0"\nedition = "2021"\n'


def _proj(tmp_path: Path, cargo: str = _CARGO, extra: dict[str, str] | None = None) -> Project:
    (tmp_path / "Cargo.toml").write_text(cargo)
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="rust", primary_build_file="Cargo.toml")


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def test_bare_crate_gets_build_clippy_test_and_no_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path), _RUST)
    assert _argv(r, "build") == [["cargo", "build"]]
    assert _argv(r, "lint") == [["cargo", "clippy"]]
    assert _argv(r, "tests") == [["cargo", "test"]]
    assert _argv(r, "coverage") == []


def test_tarpaulin_config_file_adds_coverage(tmp_path):
    for i, name in enumerate(["tarpaulin.toml", ".tarpaulin.toml"]):
        d = tmp_path / str(i)
        d.mkdir()
        r = detect_commands(_proj(d, extra={name: "[default]\n"}), _RUST)
        assert _argv(r, "coverage") == [["cargo", "tarpaulin", "--out", "Xml"]], name
        assert r.commands["coverage"][0].source == "config"


def test_tarpaulin_metadata_in_cargo_toml_adds_coverage(tmp_path):
    cargo = _CARGO + "\n[package.metadata.tarpaulin]\nout = [\"Xml\"]\n"
    r = detect_commands(_proj(tmp_path, cargo), _RUST)
    assert _argv(r, "coverage") == [["cargo", "tarpaulin", "--out", "Xml"]]


def test_tarpaulin_only_as_a_word_in_cargo_toml_does_not_count(tmp_path):
    cargo = _CARGO + "# we do not use tarpaulin here\n"
    r = detect_commands(_proj(tmp_path, cargo), _RUST)
    assert _argv(r, "coverage") == []


def test_cobertura_output_is_read_from_cobertura_xml():
    # tarpaulin --out Xml writes cobertura.xml
    assert "cobertura.xml" in _RUST["coverage_files"]
