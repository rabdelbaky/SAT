# Pre-LLM Checks: Spec (v1)

Baseline: colleague's README. Marked **[NEW]** = gap fixes we decided. Terms: see CONTEXT.md.

## 1. Purpose
Cross-platform Python script (Windows/macOS/Linux, Python 3.11+, no third-party packages). Finds projects in a repo, runs build -> lint -> tests -> coverage using only each project's own tools, writes a terminal table (humans) and `pre-llm-report.json` (AI). The tool uses no AI.

## 2. Golden rules
- Read-only: never changes code, never installs anything, never runs fixers or formatters.
- Only runs project-defined tools. No guessing from devDependencies alone.
- Commands run as argument lists (`shell=False`), from the project's folder.
- The only file it may ever change: .gitignore, and only with `--add-gitignore`.
- **[NEW]** Trust model: repo scripts are arbitrary code. README says "only run on code you trust". Every run prints the trust notice first. `--dry-run` previews without running. No prompt, no sandbox in v1.

## 3. Pipeline
1. **Input** **[NEW]**: folders only (cwd or `--path`). No zip, git URL, or single file in v1.
2. **Find projects**: scan folder tree. Skip: node_modules, .git, .next, target, build, dist, .venv, graphify-out, .ua, .pre-llm, **[NEW]** bin, obj, venv, env, vendor, out, __pycache__, coverage, plus anything in `ignore`.
   - A build file owns only files of its own language. Each file belongs to the nearest build file above it (sub-project beats root).
   - One project per folder per language. Priority: Python pyproject.toml > requirements.txt; .NET .sln > .csproj. Both stay listed in `build_files`.
3. **Find tools**: only counts if defined by a script in the build file, a plugin in the build file, a config file next to it, a built-in Maven/Gradle phase, or a pre-llm.toml override.
4. **Match scripts to stages**: exact names and prefixes (`lint`, `lint:types`). Skip names ending :fix :watch :dev :serve :e2e :docker :deploy and anything using --fix/--write; record reason in `skipped_scripts`. Identical commands run once; different args are different commands.
5. **Dependencies** **[NEW: data-driven for all languages]**: languages.toml gives each language an optional folder check and/or error phrases. Folder check runs before; phrase match on a failed run turns `fail` into `dependencies_missing` (warning). Never installs.
6. **Run safely**: prefer wrappers (mvnw/gradlew; `.cmd` on Windows). Tool missing -> `tool_not_installed` warning, stage skipped.
7. **Build gate**: Build fails or times out -> other stages for that project skipped. `--lint-anyway` still runs lint. `--steps` excluding build disables the gate. Projects are independent.
8. **Timeouts**: Build 10m, Lint 5m, Tests 15m, Coverage 15m. Override `--timeout-build` etc. (90s, 30m, 1h, 1h30m, seconds). On timeout kill the whole process tree. `timeout` counts as failure for exit code.
9. **Coverage**: read JaCoCo XML, Cobertura XML, Istanbul json-summary, lcov. Only files written during this run (freshness check). Fallback: parse percentage from output. Line coverage is main; branch if available. Per-tool results never averaged; table shows lowest. No threshold in v1. No data -> warning.

## 4. Config
- **languages.toml**: extensions, build files, stage names, config files, dependency checks, coverage paths, tested/untested. Adding a language = TOML entry only.
- **pre-llm.toml** **[NEW]** (optional, repo root, minimal):
```toml
ignore = ["legacy", "generated"]

[[project]]
path = "backend"
lint = "npm run check-style"
tests = "pytest -q"
```
Only `ignore` and per-project stage overrides in v1.

## 5. Statuses
Command/stage: `pass`, `fail`, `timeout`, `skipped`, `interrupted`, **[NEW]** `no_linter_configured`, `dependencies_missing`.
Warnings: unsupported_extension, no_project, tool_not_installed, nothing_to_run, dependencies_missing, gitignore_missing.
Worst-wins in table cells: fail > timeout > warning > pass. SKIP = did not run.

## 6. Report: pre-llm-report.json
- `schema_version: "1.0"`, summary at top, always written (even on crash: `summary.status = "error"`).
- Per command: command, scripts, source, status, duration_s, `output_tail`, log_path, **[NEW]** `findings` (optional, null in v1).
- **[NEW]** `environment`: OS plus version of each runner actually used (`unknown` if the version command fails).
- Secrets masked (tokens, API keys, passwords, connection strings). Paths relative to repo root, always forward slashes.
- **[NEW]** Size budget: `output_tail` 50 lines (`--tail-lines`), each line cut at 500 chars. `findings` max 50 per command with true total reported. Report cap about 200 KB: trim tails first, then set `"truncated": true`.
- Full logs in `.pre-llm/logs/` (gitignored; else `gitignore_missing` warning).

## 7. Terminal
One row per project: Project, Language, Build, Lint, Tests, Coverage. `[untested]` label for unverified languages. Detail lines only for non-pass; then warnings; then summary. `--verbose` streams output and shows every command.

## 8. Exit codes
0 all passed or only warnings. 1 something failed or timed out. 2 script error. 3 no supported project. **[NEW]** 130 interrupted (Ctrl+C).

## 9. Cross-platform **[NEW]**
- Resolve executables with `shutil.which` (Windows .cmd/.exe).
- Decode output as UTF-8 with replacement; never crash on odd bytes.
- Ctrl+C: kill child process tree, mark `interrupted`, still write report, exit 130.

## 10. Languages
Supported (all `[untested]` until fixtures pass): Java (Maven, Gradle), Kotlin (Gradle), JS/TS, Python, Go, C#/.NET, Rust, PHP, Ruby, Swift, C/C++. Promote to tested only when all applicable fixtures match EXPECTED.md. Build order: Python, then JS/TS, then Java, then the rest.

## 11. CLI flags
--path, --output, --dry-run, --steps, --lint-anyway, --verbose, --timeout-*, --tail-lines, --config, --add-gitignore, --version.

## 12. Testing
Black-box only: exit code, terminal table, JSON report. Fixtures in tests/fixtures/, expectations in EXPECTED.md. Per language: ok, build-fail, test-fail, lint-fail, no-tests (where applicable), plus no-linter. Shared: risky-scripts, duplicate-scripts, hang, monorepo, missing-deps, interrupted. Fixtures are run by hand, not by the agent.

## 13. Not in v1
Parallel projects, language filter, changed-files-only, coverage thresholds, installing dependencies, CI/remote integration, sandbox, zip/git/single-file input, tool-specific finding parsers (JUnit XML then SARIF readers come first later).
