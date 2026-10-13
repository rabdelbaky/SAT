"""Tests for Kotlin (Gradle) detection (Session 13).

Same rules as Java (see test_detection_java.py): built-in phases come from the
project's build tool (Gradle only), and lint/coverage run only when the build
file declares the plugin id.  A config file alone (detekt.yml) does not count:
without the plugin Gradle has no detekt task.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project, discover_projects
from pre_llm_checks import load_languages

_KOTLIN = load_languages()["kotlin"]


def _proj(tmp_path: Path, build_file: str, content: str = "", extra: dict[str, str] | None = None) -> Project:
    (tmp_path / build_file).write_text(content)
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="kotlin", primary_build_file=build_file)


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def test_bare_gradle_kts_build_and_tests_only(tmp_path):
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", 'plugins { kotlin("jvm") version "1.9.0" }'), _KOTLIN)
    assert _argv(r, "build") == [["gradle", "assemble"]]  # `gradle build` also runs test and check
    assert _argv(r, "tests") == [["gradle", "test"]]
    assert _argv(r, "lint") == []  # was `gradle check` before: no linter declared
    assert _argv(r, "coverage") == []


def test_bare_groovy_gradle(tmp_path):
    r = detect_commands(_proj(tmp_path, "build.gradle", "plugins { id 'org.jetbrains.kotlin.jvm' }"), _KOTLIN)
    assert _argv(r, "build") == [["gradle", "assemble"]]
    assert _argv(r, "lint") == []


def test_detekt_plugin_adds_lint(tmp_path):
    kts = 'plugins { kotlin("jvm")\n id("io.gitlab.arturbosch.detekt") version "1.23.0" }'
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", kts), _KOTLIN)
    assert _argv(r, "lint") == [["gradle", "detekt"]]
    assert r.commands["lint"][0].source == "config"


def test_ktlint_plugin_adds_lint(tmp_path):
    kts = 'plugins { id("org.jlleitschuh.gradle.ktlint") version "11.0.0" }'
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", kts), _KOTLIN)
    assert _argv(r, "lint") == [["gradle", "ktlintCheck"]]


def test_new_detekt_plugin_id_adds_lint(tmp_path):
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", 'plugins { id("dev.detekt") version "2.0.0" }'), _KOTLIN)
    assert _argv(r, "lint") == [["gradle", "detekt"]]


def test_lone_detekt_config_file_adds_no_lint(tmp_path):
    # Without the plugin Gradle rejects `gradle detekt` (task not found): a false Lint FAIL.
    kts = 'plugins { kotlin("jvm") }'
    for name in ("detekt.yml", "detekt.yaml", ".detekt.yml"):
        d = tmp_path / name
        d.mkdir()
        r = detect_commands(_proj(d, "build.gradle.kts", kts, {name: "build: {}"}), _KOTLIN)
        assert _argv(r, "lint") == [], name


def test_spotless_ktlint_step_adds_no_lint(tmp_path):
    # Spotless's ktlint() step adds no ktlintCheck task.
    kts = (
        'plugins { kotlin("jvm")\n id("com.diffplug.spotless") version "6.25.0" }\n'
        "spotless { kotlin { ktlint() } }\n"
    )
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", kts), _KOTLIN)
    assert _argv(r, "lint") == []


def test_detekt_plugin_only_in_a_comment_adds_no_lint(tmp_path):
    kts = (
        'plugins {\n    kotlin("jvm")\n'
        '    // id("io.gitlab.arturbosch.detekt") version "1.23.8"\n'
        '    /* id("io.gitlab.arturbosch.detekt") */\n}\n'
    )
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", kts), _KOTLIN)
    assert _argv(r, "lint") == []


def test_both_linters_run_in_rule_order(tmp_path):
    kts = 'plugins { id("io.gitlab.arturbosch.detekt")\n id("org.jlleitschuh.gradle.ktlint") }'
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", kts), _KOTLIN)
    assert _argv(r, "lint") == [["gradle", "detekt"], ["gradle", "ktlintCheck"]]


def test_jacoco_adds_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", "plugins { jacoco }"), _KOTLIN)
    assert _argv(r, "coverage") == [["gradle", "jacocoTestReport"]]


def test_no_maven_commands_ever(tmp_path):
    kts = "plugins { jacoco\n id(\"io.gitlab.arturbosch.detekt\") }"
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", kts), _KOTLIN)
    assert all(c[0] == "gradle" for s in ("build", "lint", "tests", "coverage") for c in _argv(r, s))


def test_gradle_settings_root_with_two_subprojects_is_one_project(tmp_path):
    def write(rel: str, text: str = "") -> None:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    write("settings.gradle.kts", 'include("app", "lib")')
    write("build.gradle.kts", 'plugins { kotlin("jvm") version "2.0.21" apply false }')
    write("app/build.gradle.kts")
    write("app/src/main/kotlin/app/App.kt", "object App")
    write("lib/build.gradle.kts")
    write("lib/src/main/kotlin/lib/Lib.kt", "object Lib")
    projects = discover_projects(tmp_path, load_languages())
    assert [(p.path.resolve(), p.language) for p in projects] == [(tmp_path.resolve(), "kotlin")]
