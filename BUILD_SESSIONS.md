# Build Sessions (low-quota plan)

## Rules for every session
- Fresh session each time. Agent reads only CONTEXT.md and SPEC.md plus the named files.
- Prompt template: `Read CONTEXT.md and SPEC.md. Using tdd, implement <module> in <file>. Code only, no explanations. Do not run the tool; I will.`
- The agent writes code. You run things by hand. Paste back only the mismatch, e.g. `python lint-fail: expected fail, got pass` plus the few relevant output lines.
- Use `diagnose` only for bugs you cannot solve in a few minutes.
- Never ask the agent to explore the repo. Always name the files.

## Sessions (in order)
| # | Module | Output | Manual check |
|---|---|---|---|
| 1 | Skeleton + languages.toml loader | pre_llm_checks.py, languages.toml (all languages, `untested`) | `--version`, `--dry-run` on empty folder gives exit 3 |
| 2 | Report schema, writer, secret masking, size caps | report writer | Fake data: report written, caps and `truncated` work |
| 3 | CLI, path validation, trust notice | arg parsing | Bad flags, bad path, notice printed first |
| 4 | Project discovery (skips, monorepo, priority) | discovery | `monorepo` fixture matches EXPECTED.md |
| 5 | Tool and script detection + pre-llm.toml | detection | `risky-scripts`, `duplicate-scripts`, override and ignore |
| 6 | Safe runner (shell=False, timeout, kill tree, encoding, Ctrl+C) | runner | `hang` fixture, press Ctrl+C: report written, exit 130 |
| 7 | Stage orchestration (build gate, dependency check, statuses) | orchestrator | `missing-deps`, `build-fail`, `no_linter_configured` |
| 8 | Coverage readers + freshness | coverage | Python then JS fixtures: stale file ignored |
| 9 | Terminal table, exit codes, environment block | output | Compare table to EXPECTED.md |
| 10 | Fixtures: Python | tests/fixtures/python-* | Tick checklist |
| 11 | Fixtures: JS/TS | tests/fixtures/js-* | Tick checklist |
| 12 | Fixtures: Java | tests/fixtures/java-* | Tick checklist |
| 13+ | Remaining languages | one session each | Tick checklist |
| 20 | Python coverage from pytest addopts (`--cov` in addopts runs `pytest --cov-report=xml`; `exclusive` rule key) | detection.py, languages.toml, tests/fixtures/python-cov-* | `python-cov-addopts` Coverage 83.3%, `python-cov-both` `--dry-run` |
| 21 | Report counts, fake-tool golden tests, schema guard, README (`summary.counts` + `summary.generated_at`; `run_command` faked for 17 fixtures incl. generated C/C++; report key-path golden) | output.py, pre_llm_checks.py, tests/test_fake_runs.py, tests/test_report_schema.py, tests/golden_files.py, README.md | `UPDATE_GOLDEN=1` on Windows, review `tests/golden/`, commit; then plain `pytest` on Mac matches |

Fixtures (10 to 13+) are tiny; ask the agent for several languages per session if quota allows. Split fixture ownership with your colleague and share results.

## Language checklist (a language becomes `tested` only when every applicable box is ticked)
| Language | ok | build-fail | test-fail | lint-fail | no-tests | no-linter | Tested? |
|---|---|---|---|---|---|---|---|
| Python | [x] | n/a | [x] | [x] | [x] | [x] | yes |
| JS/TS | [x] | [x] | [x] | [x] | [x] | [x] | yes |
| Java | [x] | [x] | [x] | [x] | [x] | [x] | yes |
| Kotlin | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | no |
| Go | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | no |
| C#/.NET | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | no |
| Rust | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | no |
| PHP | [ ] | n/a | [ ] | [ ] | [ ] | [ ] | no |
| Ruby | [ ] | n/a | [ ] | [ ] | [ ] | [ ] | no |
| Swift | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | no |
| C/C++ | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | no |

Shared fixtures: [ ] risky-scripts [ ] duplicate-scripts [ ] hang [ ] monorepo [ ] missing-deps [ ] interrupted
