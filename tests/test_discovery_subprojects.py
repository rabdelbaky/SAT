"""Tests for Maven modules and Gradle subprojects (Session 12).

A Maven module (listed in a parent pom.xml <module>) or a Gradle subproject
(below a folder with settings.gradle / settings.gradle.kts) is built by the
root build.  Reporting it as its own project builds it twice and, for a
module that depends on a sibling, shows a false dependencies_missing (the
sibling is only on the classpath inside the root build).  Rule (languages.toml
subproject_rules): such a folder is part of the root project.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from discovery import discover_projects
from pre_llm_checks import load_languages

_LANGS = load_languages()

_PARENT = (
    '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
    "<packaging>pom</packaging>{modules}</project>"
)
_CHILD = "<project><modelVersion>4.0.0</modelVersion></project>"


def _rel(root: Path) -> list[str]:
    return [
        p.path.relative_to(root).as_posix() or "."
        for p in discover_projects(root, _LANGS)
    ]


def _write(root: Path, rel: str, text: str = "") -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)


def _modules(*names: str) -> str:
    return "<modules>" + "".join(f"<module>{n}</module>" for n in names) + "</modules>"


def test_maven_modules_are_part_of_the_root_project(tmp_path):
    _write(tmp_path, "pom.xml", _PARENT.format(modules=_modules("a", "b")))
    _write(tmp_path, "a/pom.xml", _CHILD)
    _write(tmp_path, "b/pom.xml", _CHILD)
    assert _rel(tmp_path) == ["."]


def test_nested_maven_modules_and_pom_file_entries(tmp_path):
    _write(tmp_path, "pom.xml", _PARENT.format(modules=_modules("libs/pom.xml")))
    _write(tmp_path, "libs/pom.xml", _PARENT.format(modules=_modules("core")))
    _write(tmp_path, "libs/core/pom.xml", _CHILD)
    assert _rel(tmp_path) == ["."]


def test_maven_modules_inside_a_profile_count(tmp_path):
    body = "<profiles><profile><id>all</id>" + _modules("extra") + "</profile></profiles>"
    _write(tmp_path, "pom.xml", _PARENT.format(modules=body))
    _write(tmp_path, "extra/pom.xml", _CHILD)
    assert _rel(tmp_path) == ["."]


def test_maven_folder_not_listed_as_module_stays_its_own_project(tmp_path):
    _write(tmp_path, "pom.xml", _PARENT.format(modules=_modules("a")))
    _write(tmp_path, "a/pom.xml", _CHILD)
    _write(tmp_path, "tools/pom.xml", _CHILD)
    assert _rel(tmp_path) == [".", "tools"]


def test_invalid_parent_pom_keeps_every_project(tmp_path):
    _write(tmp_path, "pom.xml", "<project><modules><module>a</module>")
    _write(tmp_path, "a/pom.xml", _CHILD)
    assert _rel(tmp_path) == [".", "a"]


def test_gradle_subprojects_are_part_of_the_root_project(tmp_path):
    _write(tmp_path, "settings.gradle", "include 'app', 'lib'")
    _write(tmp_path, "build.gradle")
    _write(tmp_path, "app/build.gradle.kts")
    _write(tmp_path, "lib/build.gradle")
    _write(tmp_path, "app/src/main/java/App.java")
    assert _rel(tmp_path) == ["."]


def test_gradle_folder_with_its_own_settings_stays_its_own_project(tmp_path):
    _write(tmp_path, "settings.gradle.kts")
    _write(tmp_path, "build.gradle.kts")
    _write(tmp_path, "included/settings.gradle")
    _write(tmp_path, "included/build.gradle")
    assert _rel(tmp_path) == [".", "included"]


def test_settings_only_root_keeps_subprojects(tmp_path):
    # No root build file: there is no root project to own the subprojects.
    _write(tmp_path, "settings.gradle", "include 'app'")
    _write(tmp_path, "app/build.gradle")
    assert _rel(tmp_path) == ["app"]


def test_other_languages_are_not_affected(tmp_path):
    _write(tmp_path, "pom.xml", _PARENT.format(modules=_modules("web")))
    _write(tmp_path, "web/package.json", "{}")
    rel = [
        (p.path.relative_to(tmp_path).as_posix() or ".", p.language)
        for p in discover_projects(tmp_path, _LANGS)
    ]
    assert rel == [(".", "java"), ("web", "javascript")]
