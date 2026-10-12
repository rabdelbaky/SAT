"""Unit tests for the load_languages() public function.

Seam: load_languages(path) -> dict
"""

import tempfile
import textwrap
from pathlib import Path

import pytest

# Import the public function directly (not the CLI).
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from pre_llm_checks import load_languages, LanguagesLoadError

_EXPECTED_LANGUAGES = {
    "python",
    "javascript",  # JS/TS shares one entry
    "java",
    "kotlin",
    "go",
    "csharp",  # C#/.NET
    "rust",
    "php",
    "ruby",
    "swift",
    "cpp",  # C/C++
}


def _make_toml(languages: dict[str, dict]) -> Path:
    """Write a minimal languages.toml to a temp file and return its path."""
    lines = []
    for name, fields in languages.items():
        lines.append(f"[language.{name}]")
        for k, v in fields.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, list):
                items = ", ".join(f'"{i}"' for i in v)
                lines.append(f"{k} = [{items}]")
            else:
                lines.append(f'{k} = "{v}"')
        lines.append("")
    tmp = Path(tempfile.mktemp(suffix=".toml"))
    tmp.write_text("\n".join(lines), encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# Cycle 3: load_languages behaviour
# ---------------------------------------------------------------------------


def test_load_languages_returns_all_11_languages():
    langs = load_languages()
    assert set(langs.keys()) == _EXPECTED_LANGUAGES


def test_all_languages_are_untested_by_default():
    langs = load_languages()
    for name, entry in langs.items():
        assert entry.get("tested") is False, (
            f"Language {name!r} has tested={entry.get('tested')!r}, expected False"
        )


def test_load_languages_missing_tested_field_defaults_false():
    """tested defaults to False even when the TOML entry omits it."""
    tmp = _make_toml({"python": {"extensions": [".py"]}})
    try:
        langs = load_languages(tmp)
        assert langs["python"]["tested"] is False
    finally:
        tmp.unlink(missing_ok=True)


def test_load_languages_accepts_explicit_tested_true():
    """If a TOML entry says tested = true, that value is preserved."""
    tmp = _make_toml({"python": {"extensions": [".py"], "tested": True}})
    try:
        langs = load_languages(tmp)
        assert langs["python"]["tested"] is True
    finally:
        tmp.unlink(missing_ok=True)


def test_load_languages_raises_languages_load_error_on_missing_file():
    with pytest.raises(LanguagesLoadError):
        load_languages(Path("/nonexistent/languages.toml"))


def test_load_languages_raises_languages_load_error_on_malformed_toml():
    tmp = Path(tempfile.mktemp(suffix=".toml"))
    try:
        tmp.write_text("this is not [ valid toml !!!", encoding="utf-8")
        with pytest.raises(LanguagesLoadError):
            load_languages(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def test_load_languages_error_message_contains_reason():
    path = Path("/nonexistent/languages.toml")
    with pytest.raises(LanguagesLoadError) as exc_info:
        load_languages(path)
    assert (
        str(path) in str(exc_info.value)
        or "languages.toml" in str(exc_info.value).lower()
    )


# ---------------------------------------------------------------------------
# dep_error_phrases only signal "packages are not installed" (SPEC §3.5)
# ---------------------------------------------------------------------------

# Text that shows up in ordinary build/test failures.  A dep_error_phrase that
# matches any of these would turn a real code failure into a warning.
_ORDINARY_FAILURE_TEXT = [
    "BUILD FAILURE",
    "npm ERR!",
    "error[E",
    "could not compile",
    "fatal error:",
    "No such file or directory",
]


@pytest.mark.parametrize("failure_text", _ORDINARY_FAILURE_TEXT)
def test_no_dep_error_phrase_matches_ordinary_failure_text(failure_text):
    languages = load_languages()
    offenders = [
        (name, phrase)
        for name, entry in languages.items()
        for phrase in entry.get("dep_error_phrases", [])
        if failure_text in phrase or phrase in failure_text
    ]
    assert offenders == [], (
        f"dep_error_phrases would match ordinary failure text "
        f"{failure_text!r}: {offenders}"
    )
