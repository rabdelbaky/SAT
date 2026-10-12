"""Guard: `dep_error_phrases` must only match genuinely-missing-dependency output.

When a failed command's output contains any phrase, the orchestrator turns `fail`
into `dependencies_missing` (a warning, exit 0).  A phrase that the tool also
prints for an ordinary build/test/lint failure would hide real failures, e.g.:

  - Maven prints "BUILD FAILURE" for ANY failed build
  - rustc prints "could not compile" / "error[E....]" for ANY compile error
  - npm <= 10 prints "npm ERR!" for ANY failing script
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator import _matches_dep_error
from pre_llm_checks import load_languages

_LANGS = load_languages()

# Output of ordinary failures: none of these may be classified as missing dependencies.
_ORDINARY_FAILURES = {
    "java": ["[ERROR] COMPILATION ERROR", "[ERROR] Tests run: 1, Failures: 1", "[INFO] BUILD FAILURE"],
    "kotlin": ["e: Calc.kt: (3, 5): Unresolved reference: foo", "FAILURE: Build failed with an exception.", "BUILD FAILED in 2s"],
    "rust": ["error[E0308]: mismatched types", "error: could not compile `calc` (lib) due to 1 previous error",
             "test tests::adds ... FAILED"],
    "javascript": ["npm ERR! Lifecycle script `test` failed", "npm error code 1", "AssertionError [ERR_ASSERTION]"],
    "python": ["AssertionError: 5 != 6", "SyntaxError: invalid syntax"],
    "go": ["--- FAIL: TestAdd (0.00s)", "./calc.go:4:15: syntax error: unexpected ;"],
    "csharp": ["error CS1002: ; expected", "Failed!  - Failed: 1, Passed: 0"],
    "swift": ["Sources/Calc/Calc.swift:2:9: error: expected expression after operator",
              "error: cannot find 'foo' in scope", "Test Case '-[CalcTests.CalcTests testSum]' failed (0.001 seconds)."],
    "ruby": ["calc.rb:3: syntax error, unexpected end-of-input",
             "Failure:\nCalcTest#test_add [test_calc.rb:5]:\nExpected: 6\n  Actual: 5"],
    "php": ["PHP Parse error:  syntax error, unexpected '}' in calc.php on line 3",
            "FAILURES!\nTests: 1, Assertions: 1, Failures: 1.",
            "Warning: include(data.txt): Failed to open stream: No such file or directory"],
}

# Output of genuinely missing dependencies: these must be recognised.
_MISSING_DEPENDENCIES = {
    "java": ["[ERROR] Failed to execute goal on project x: Could not resolve dependencies for project x"],
    "kotlin": ["> Could not resolve org.jetbrains.kotlin:kotlin-stdlib:1.9.0."],
    "rust": ["error: no matching package named `serde` found", "error: failed to select a version for the requirement `rand = \"^9\"`",
             "error: failed to download from `https://index.crates.io/config.json`"],
    "javascript": ["Error: Cannot find module 'jest'", "sh: eslint: command not found"],
    "python": ["ModuleNotFoundError: No module named 'pytest'"],
    "go": ["cannot find module providing package github.com/x/y"],
    "csharp": ["error NU1101: Unable to find package Foo. No packages exist with this id"],
    "swift": ["error: no such module 'Alamofire'", "error: missing package 'foo' at https://github.com/x/foo"],
    "ruby": ["Could not find gem 'rspec' in locally installed gems.",
             "cannot load such file -- rspec/core (LoadError)"],
    "php": ["PHP Fatal error:  Uncaught Error: Failed opening required 'vendor/autoload.php'",
            "Your requirements could not be resolved to an installable set of packages."],
}


@pytest.mark.parametrize("lang", sorted(_ORDINARY_FAILURES))
def test_ordinary_failures_are_not_dependency_errors(lang):
    phrases = _LANGS[lang]["dep_error_phrases"]
    for output in _ORDINARY_FAILURES[lang]:
        assert not _matches_dep_error(output, phrases), f"{lang}: {output!r} matched {phrases}"


@pytest.mark.parametrize("lang", sorted(_MISSING_DEPENDENCIES))
def test_missing_dependencies_are_recognised(lang):
    phrases = _LANGS[lang]["dep_error_phrases"]
    for output in _MISSING_DEPENDENCIES[lang]:
        assert _matches_dep_error(output, phrases), f"{lang}: {output!r} not matched by {phrases}"
