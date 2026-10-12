"""Tests for build files claimed by more than one language (Session 12).

`build.gradle` / `build.gradle.kts` are listed for both java and kotlin.  Before
this rule every Gradle project was reported twice (once per language) and ran
every stage twice.  Rule: when several languages claim the same primary build
file in a folder, keep the ones whose source extensions exist under that folder;
if none do, keep the first language declared in languages.toml (java).
Build files claimed by one language are never affected.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from discovery import discover_projects
from pre_llm_checks import load_languages

_LANGS = load_languages()


def _langs(root: Path) -> list[str]:
    return [p.language for p in discover_projects(root, _LANGS)]


def _write(root: Path, rel: str, text: str = "") -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)


def test_gradle_with_java_sources_is_java_only(tmp_path):
    _write(tmp_path, "build.gradle")
    _write(tmp_path, "src/main/java/App.java")
    assert _langs(tmp_path) == ["java"]


def test_gradle_kts_with_kotlin_sources_is_kotlin_only(tmp_path):
    _write(tmp_path, "build.gradle.kts")
    _write(tmp_path, "src/main/kotlin/App.kt")
    assert _langs(tmp_path) == ["kotlin"]


def test_gradle_with_both_kinds_of_sources_is_both(tmp_path):
    _write(tmp_path, "build.gradle.kts")
    _write(tmp_path, "src/main/java/Foo.java")
    _write(tmp_path, "src/main/kotlin/Bar.kt")
    assert sorted(_langs(tmp_path)) == ["java", "kotlin"]


def test_gradle_without_any_sources_falls_back_to_first_declared_language(tmp_path):
    _write(tmp_path, "build.gradle")
    assert _langs(tmp_path) == ["java"]


def test_maven_is_unaffected(tmp_path):
    _write(tmp_path, "pom.xml")
    assert _langs(tmp_path) == ["java"]


def test_sources_in_skipped_folders_do_not_count(tmp_path):
    _write(tmp_path, "build.gradle.kts")
    _write(tmp_path, "build/generated/Gen.kt")  # build/ is a skipped folder
    _write(tmp_path, "src/main/java/App.java")
    assert _langs(tmp_path) == ["java"]


def test_unshared_build_files_in_one_folder_stay_separate_projects(tmp_path):
    _write(tmp_path, "package.json", "{}")
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    assert sorted(_langs(tmp_path)) == ["javascript", "python"]


def test_gradle_kts_build_script_is_not_a_kotlin_source(tmp_path):
    # .kts is a Kotlin extension, but build.gradle.kts / settings.gradle.kts are build files.
    _write(tmp_path, "build.gradle.kts")
    _write(tmp_path, "settings.gradle.kts")
    _write(tmp_path, "src/main/java/App.java")
    assert _langs(tmp_path) == ["java"]
