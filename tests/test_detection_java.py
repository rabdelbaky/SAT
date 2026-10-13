"""Tests for Java (Maven/Gradle) detection (Session 12).

Seam: detection.detect_commands(project, lang_cfg) with the real languages.toml
entry for java.  Rules under test:

- Built-in lifecycle phases are chosen by the project's build tool: a Maven
  project (pom.xml) gets `mvn ...`, a Gradle project gets `gradle ...`.
  Never the other tool's commands.
- Lint and coverage are NOT built-in: they run only when the build file
  declares the plugin, per SPEC §3 step 3.  A lone checkstyle.xml / pmd.xml
  does not count: Maven ignores it unless pom.xml configures the plugin.
- A plugin named only in a comment of the build file is not declared.
- Gradle's build command is `gradle assemble`: `gradle build` would also run
  test and check, hiding test and lint failures behind the build gate.  A bare pom.xml / build.gradle therefore has no lint command
  (-> no_linter_configured) and no coverage command.
- The wrapper (mvnw / gradlew) is chosen later by the runner, so detection
  always emits plain `mvn` / `gradle`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project
from pre_llm_checks import load_languages

_JAVA = load_languages()["java"]

_POM = "<project><modelVersion>4.0.0</modelVersion>{body}</project>"


def _proj(tmp_path: Path, build_file: str, content: str, extra: dict[str, str] | None = None) -> Project:
    (tmp_path / build_file).write_text(content)
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="java", primary_build_file=build_file)


def _maven(tmp_path, plugins: str = "", extra=None) -> Project:
    body = f"<build><plugins>{plugins}</plugins></build>" if plugins else ""
    return _proj(tmp_path, "pom.xml", _POM.format(body=body), extra)


def _plugin(artifact: str) -> str:
    return f"<plugin><artifactId>{artifact}</artifactId></plugin>"


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


# --- Maven ------------------------------------------------------------------


def test_bare_maven_gets_build_and_tests_only(tmp_path):
    r = detect_commands(_maven(tmp_path), _JAVA)
    assert _argv(r, "build") == [["mvn", "compile"]]
    assert _argv(r, "tests") == [["mvn", "test"]]
    assert _argv(r, "lint") == []
    assert _argv(r, "coverage") == []
    assert r.commands["build"][0].source == "builtin"


def test_maven_checkstyle_plugin_adds_lint(tmp_path):
    r = detect_commands(_maven(tmp_path, _plugin("maven-checkstyle-plugin")), _JAVA)
    assert _argv(r, "lint") == [["mvn", "checkstyle:check"]]
    assert r.commands["lint"][0].source == "config"


def test_maven_pmd_and_spotbugs_plugins(tmp_path):
    plugins = _plugin("maven-pmd-plugin") + _plugin("spotbugs-maven-plugin")
    r = detect_commands(_maven(tmp_path, plugins), _JAVA)
    assert _argv(r, "lint") == [["mvn", "pmd:check"], ["mvn", "spotbugs:check"]]


def test_maven_lint_config_file_alone_adds_nothing(tmp_path):
    extra = {"checkstyle.xml": "<module/>", "pmd.xml": "<ruleset/>", ".checkstyle": "x"}
    r = detect_commands(_maven(tmp_path, extra=extra), _JAVA)
    assert _argv(r, "lint") == []


def test_maven_plugin_in_xml_comment_is_not_declared(tmp_path):
    plugins = "<!-- " + _plugin("maven-checkstyle-plugin") + " -->\n<!--\n" + _plugin("jacoco-maven-plugin") + "\n-->"
    r = detect_commands(_maven(tmp_path, plugins), _JAVA)
    assert _argv(r, "lint") == [] and _argv(r, "coverage") == []


def test_maven_jacoco_plugin_adds_coverage(tmp_path):
    r = detect_commands(_maven(tmp_path, _plugin("jacoco-maven-plugin")), _JAVA)
    assert _argv(r, "coverage") == [["mvn", "jacoco:report"]]


def test_maven_unrelated_plugin_adds_nothing(tmp_path):
    r = detect_commands(_maven(tmp_path, _plugin("maven-compiler-plugin")), _JAVA)
    assert _argv(r, "lint") == [] and _argv(r, "coverage") == []


def test_maven_does_not_get_gradle_rules(tmp_path):
    # a pom that merely mentions "checkstyle" in a comment is still Maven
    r = detect_commands(_maven(tmp_path, _plugin("maven-checkstyle-plugin")), _JAVA)
    assert all(c[0] == "mvn" for stage in ("build", "lint", "tests") for c in _argv(r, stage))


# --- Gradle -----------------------------------------------------------------


def test_bare_gradle_gets_gradle_commands_not_maven(tmp_path):
    for i, bf in enumerate(["build.gradle", "build.gradle.kts"]):
        d = tmp_path / str(i)
        d.mkdir()
        r = detect_commands(_proj(d, bf, "plugins { id 'java' }"), _JAVA)
        assert _argv(r, "build") == [["gradle", "assemble"]], bf
        assert _argv(r, "tests") == [["gradle", "test"]], bf
        assert _argv(r, "lint") == [] and _argv(r, "coverage") == [], bf


def test_gradle_lint_plugins(tmp_path):
    gradle = "plugins { id 'java'\n id 'checkstyle'\n id 'pmd'\n id 'com.github.spotbugs' version '6' }"
    r = detect_commands(_proj(tmp_path, "build.gradle", gradle), _JAVA)
    assert _argv(r, "lint") == [
        ["gradle", "checkstyleMain"],
        ["gradle", "pmdMain"],
        ["gradle", "spotbugsMain"],
    ]


def test_gradle_kotlin_dsl_jacoco(tmp_path):
    kts = 'plugins { java\n jacoco }'
    r = detect_commands(_proj(tmp_path, "build.gradle.kts", kts), _JAVA)
    assert _argv(r, "coverage") == [["gradle", "jacocoTestReport"]]


def test_gradle_plugin_in_comment_is_not_declared(tmp_path):
    gradle = (
        "plugins {\n  id 'java'\n  // id 'checkstyle'\n  /* id 'pmd'\n  id 'jacoco' */\n}\n"
        "repositories { maven { url 'https://example.com/spotbugs' } }\n"
    )
    r = detect_commands(_proj(tmp_path, "build.gradle", gradle), _JAVA)
    assert _argv(r, "lint") == [] and _argv(r, "coverage") == []


def test_gradle_does_not_get_maven_rules(tmp_path):
    r = detect_commands(_proj(tmp_path, "build.gradle", "plugins { id 'checkstyle' }"), _JAVA)
    assert all(c[0] == "gradle" for stage in ("build", "lint", "tests") for c in _argv(r, stage))


# --- general ------------------------------------------------------------------


def test_pom_wins_when_both_build_files_exist(tmp_path):
    (tmp_path / "build.gradle").write_text("plugins { id 'checkstyle' }")
    r = detect_commands(_maven(tmp_path), _JAVA)  # primary_build_file is pom.xml
    assert _argv(r, "lint") == []
    assert _argv(r, "tests") == [["mvn", "test"]]


def test_unreadable_or_missing_build_file_does_not_crash(tmp_path):
    proj = Project(path=tmp_path, language="java", primary_build_file="pom.xml")  # file absent
    r = detect_commands(proj, _JAVA)
    assert _argv(r, "lint") == []


def test_script_free_language_without_build_tools_key_keeps_old_builtin_behaviour(tmp_path):
    cfg = {"stages": ["build"], "builtin_phases": {"build": ["tool one", "tool two"]}}
    proj = Project(path=tmp_path, language="x", primary_build_file="b")
    assert _argv(detect_commands(proj, cfg), "build") == [["tool", "one"]]
