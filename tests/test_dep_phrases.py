"""Guard: `dep_error_phrases` / `dep_error_patterns` must only match genuinely-missing-dependency output.

When a failed command's output contains any phrase or matches any pattern, the orchestrator turns `fail`
into `dependencies_missing` (a warning, exit 0).  A phrase that the tool also
prints for an ordinary build/test/lint failure would hide real failures, e.g.:

  - Maven prints "BUILD FAILURE" for ANY failed build
  - rustc prints "could not compile" / "error[E....]" for ANY compile error
  - cargo prints "no matching package" for a misspelt crate name
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
             "test tests::adds ... FAILED", "error: no matching package named `serdee` found",
             "error: failed to select a version for the requirement `rand = \"^9\"`",
             "error: failed to get `foo` as a dependency of package `x v0.1.0 (/p/x)`\n"
             "  unable to update /p/nonexistent_foo",
             "error: linking with `cc` failed: exit status: 1"],
    "javascript": ["npm ERR! Lifecycle script `test` failed", "npm error code 1", "AssertionError [ERR_ASSERTION]"],
    "python": ["AssertionError: 5 != 6", "SyntaxError: invalid syntax"],
    "go": ["--- FAIL: TestAdd (0.00s)", "./calc.go:4:15: syntax error: unexpected ;"],
    "csharp": ["error CS1002: ; expected", "Failed!  - Failed: 1, Passed: 0"],
    "ruby": ["calc.rb:3: syntax error, unexpected end-of-input",
             "Failure:\nCalcTest#test_add [test_calc.rb:5]:\nExpected: 6\n  Actual: 5",
             "test_calc.rb:4:in `require_relative': cannot load such file -- /home/u/p/calcc (LoadError)",
             "test_calc.rb:4:in `require_relative': cannot load such file -- C:/Users/u/p/calcc (LoadError)",
             "1 example, 1 failure"],
    "php": ["PHP Parse error:  syntax error, unexpected '}' in calc.php on line 3",
            "FAILURES!\nTests: 1, Assertions: 1, Failures: 1.",
            "Warning: include(data.txt): Failed to open stream: No such file or directory",
            "Failed asserting that 5 is identical to 6."],
}

# Output of genuinely missing dependencies: these must be recognised.
_MISSING_DEPENDENCIES = {
    "java": ["[ERROR] Failed to execute goal on project x: Could not resolve dependencies for project x"],
    "kotlin": ["> Could not resolve all files for configuration ':compileClasspath'."],
    "rust": ["error: failed to download from `https://static.crates.io/crates/itoa/1.0.18/download`",
             "  unable to update registry `crates-io`", "  unable to update https://github.com/dtolnay/itoa",
             "note: offline mode (via `--offline`) can sometimes cause surprising resolution failures",
             "  x@0.1.0 requires rustc 1.999", "error: no such command: `tarpaulin`",
             "error: 'cargo-clippy' is not installed for the toolchain 'stable-x86_64-unknown-linux-gnu'.",
             "error: linker `link.exe` not found", "error: linker `cc` not found"],
    "javascript": ["Error: Cannot find module 'jest'", "sh: eslint: command not found"],
    "python": ["ModuleNotFoundError: No module named 'pytest'"],
    "go": ['go: github.com/google/uuid@v1.6.0: Get "https://proxy.golang.org/github.com/google/uuid/@v/v1.6.0.zip": Forbidden',
           "module lookup disabled by GOPROXY=off"],
    "csharp": ["error NU1101: Unable to find package Foo. No packages exist with this id"],
    "ruby": ["Could not find gem 'rspec' in locally installed gems.",
             "cannot load such file -- minitest/autorun (LoadError)",
             "bundler: command not found: rspec\nInstall missing gem executables with `bundle install`",
             "Could not find rspec-3.13.0 in locally installed gems (Bundler::GemNotFound)",
             "Could not find rspec-3.13.0 in locally installed gems\nRun `bundle install` to install missing gems.",
             "Could not find 'rspec' (>= 0) among 70 total gem(s) (Gem::MissingSpecError)"],
    "php": ["PHP Fatal error:  Uncaught Error: Failed opening required 'vendor/autoload.php'",
            "1) No code coverage driver available", "No code coverage driver is available",
            "1) XDEBUG_MODE=coverage (environment variable) or xdebug.mode=coverage "
            "(PHP configuration setting) has to be set"],
}


@pytest.mark.parametrize("lang", sorted(_ORDINARY_FAILURES))
def test_ordinary_failures_are_not_dependency_errors(lang):
    cfg = _LANGS[lang]
    for output in _ORDINARY_FAILURES[lang]:
        assert not _matches_dep_error(
            output, cfg["dep_error_phrases"], cfg.get("dep_error_patterns", [])
        ), f"{lang}: {output!r} matched a dependency phrase or pattern"


@pytest.mark.parametrize("lang", sorted(_MISSING_DEPENDENCIES))
def test_missing_dependencies_are_recognised(lang):
    cfg = _LANGS[lang]
    for output in _MISSING_DEPENDENCIES[lang]:
        assert _matches_dep_error(
            output, cfg["dep_error_phrases"], cfg.get("dep_error_patterns", [])
        ), f"{lang}: {output!r} not matched by any dependency phrase or pattern"
