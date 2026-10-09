# Pre-LLM Checks: Context (glossary)

Terms only. No implementation details. See SPEC.md for behavior.

- **Pre-LLM Checks**: the tool. Before an AI reviews a repo, it gathers evidence: does it build, lint, pass tests, and how much is covered. It uses no AI itself.
- **Evidence**: facts the tool reports. It never fixes, installs, formats, or judges.
- **Check Run**: one invocation of the tool against one folder.
- **Project**: a folder containing a build file. It owns only the source files of its own language. One project per folder per language.
- **Build file**: a file that marks a project (package.json, pom.xml, pyproject.toml, ...).
- **Stage**: one of Build, Lint, Tests, Coverage.
- **Project-defined tool**: a command or config the project itself declares (a script, a plugin, a config file, a built-in Maven/Gradle phase). The only kind of tool the tool will run.
- **Override**: a command written in pre-llm.toml that replaces what would have been detected. Counts as project-defined.
- **pre-llm.toml**: optional file at the repo root, written by the repo owner. Supports `ignore` and per-project command overrides only.
- **languages.toml**: the rulebook. All per-language rules live here. Adding a language means adding an entry, not code.
- **Supported**: a language has an entry in languages.toml, so the tool tries to run it.
- **Tested**: a supported language that passed all its applicable fixtures. Everything else is shown as `[untested]`.
- **Fixture**: a tiny fake project in tests/fixtures/ with a known expected result listed in EXPECTED.md.
- **Report**: the machine-readable pre-llm-report.json the AI reads. Separate from the human terminal table.
- **Finding**: one parsed problem (file, line, rule, severity, message). Optional. Present only when a reader exists for that tool's output.
- **output_tail**: the last N lines of a command's raw output, always kept in the report.
- **Build gate**: if Build fails or times out, the other stages for that project are skipped.
- **no_linter_configured**: the project defines no lint tool, so the Lint stage has nothing to run. Not a pass, not a failure.
- **dependencies_missing**: packages are not installed. A setup problem, reported as a warning, never as a code failure.
- **Trust notice**: one line printed at the start of every Check Run: the tool is about to execute scripts defined by the project in that folder.
- **Trust model**: the tool is read-only, but the project's own scripts are not. Meant for code you trust. No sandbox in v1.
- **Environment block**: the OS plus the version of each runner actually used, recorded in the report.
