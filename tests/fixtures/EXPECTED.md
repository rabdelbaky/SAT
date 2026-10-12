# tests/fixtures/EXPECTED.md

Discovery expectations for the `monorepo` fixture.
Each entry is what `discover_projects` must return for that fixture folder.

---

## monorepo

**Fixture layout** (paths relative to `tests/fixtures/monorepo/`):

```
package.json                          ← root JS project
index.ts
packages/
  api/
    package.json                      ← sub-project JS
    index.ts
  ui/
    package.json                      ← sub-project JS
    Button.tsx
services/
  worker/
    go.mod                            ← Go sub-project
    main.go
  ml/
    pyproject.toml                    ← Python sub-project (priority winner)
    requirements.txt                  ← Python build file (lower priority, kept in build_files)
    train.py
node_modules/
  lodash/
    package.json                      ← SKIPPED (node_modules is a skip folder)
build/
  classes/
    pyproject.toml                    ← SKIPPED (build is a skip folder)
.git/
  HEAD                                ← SKIPPED (.git is a skip folder)
dist/                                 ← SKIPPED (dist is a skip folder)
```

**Expected projects** (4 total, ordered by path):

| Path (relative to fixture root) | Language   | Primary build file   | All build_files                           | tested   |
|---------------------------------|------------|----------------------|-------------------------------------------|----------|
| `.`                             | javascript | `package.json`       | `["package.json"]`                        | false    |
| `packages/api`                  | javascript | `package.json`       | `["package.json"]`                        | false    |
| `packages/ui`                   | javascript | `package.json`       | `["package.json"]`                        | false    |
| `services/ml`                   | python     | `pyproject.toml`     | `["pyproject.toml", "requirements.txt"]`  | false    |
| `services/worker`               | go         | `go.mod`             | `["go.mod"]`                              | false    |

**Total: 5 projects**

**Skipped folders** (no projects found inside them):
- `node_modules/` — skip rule
- `build/` — skip rule
- `.git/` — skip rule
- `dist/` — empty

**Priority check** (`services/ml`):
- Both `pyproject.toml` and `requirements.txt` exist.
- `pyproject.toml` wins (first in `build_priority` for python).
- Both filenames appear in `build_files`.
- Only **one** Python project is reported for `services/ml` (not two).

**File ownership** (nearest build file wins):
- `index.ts` at root belongs to `.` (javascript), not to any sub-package.
- `packages/api/index.ts` belongs to `packages/api` (javascript).
- `packages/ui/Button.tsx` belongs to `packages/ui` (javascript).
- `services/worker/main.go` belongs to `services/worker` (go).
- `services/ml/train.py` belongs to `services/ml` (python).

**--dry-run output** (one line per project, format: `<path>  <language>  <build_files>  [untested]`):

```
.  javascript  package.json  [untested]
packages/api  javascript  package.json  [untested]
packages/ui  javascript  package.json  [untested]
services/ml  python  pyproject.toml, requirements.txt  [untested]
services/worker  go  go.mod  [untested]
```

*(All languages are `[untested]` until fixtures pass; exact whitespace may vary.)*

**No-project exit code**: running the tool against an empty folder must exit 3
and print `No supported projects found.` to stderr.

---

## risky-scripts

**Fixture layout** (relative to `tests/fixtures/risky-scripts/`):

```
package.json          ← JS project with risky scripts
.eslintrc.js          ← ESLint config (lint stage detected via config file)
```

**`package.json` scripts:**

| Script name | Command | Expected action |
|---|---|---|
| `lint` | `eslint .` | **kept** → lint stage |
| `lint:fix` | `eslint . --fix` | **skipped** — name ends `:fix` |
| `check` | `eslint . --fix` | **skipped** — command uses `--fix` |
| `test:watch` | `jest --watch` | **skipped** — name ends `:watch` |
| `dev` | `node server.js` | **skipped** — name matches skip name (`dev`) |
| `test` | `jest` | **kept** → tests stage |
| `format` | `prettier --write .` | **skipped** — command uses `--write` |

**Expected detected commands (per stage):**

| Stage | Command (as arg list) | Source |
|---|---|---|
| `lint` | `["npm", "run", "lint"]` | `script:lint` |
| `tests` | `["npm", "run", "test"]` | `script:test` |

**Expected `skipped_scripts`:**

| Name | Reason |
|---|---|
| `lint:fix` | name ends `:fix` |
| `check` | command uses `--fix` |
| `test:watch` | name ends `:watch` |
| `dev` | name matches skip name (`dev`) |
| `format` | command uses `--write` |

**No `build` stage** — no build script and no build config detected.
**No `coverage` stage** — no coverage script or config detected.

---

## duplicate-scripts

**Fixture layout** (relative to `tests/fixtures/duplicate-scripts/`):

```
package.json    ← JS project with duplicate and near-duplicate test and lint scripts
```

**`package.json` scripts:**

| Script name | Command |
|---|---|
| `test` | `jest` |
| `test:ci` | `jest` |
| `test:coverage` | `jest --ci` |
| `lint` | `eslint .` |
| `lint:check` | `eslint .` |

**Expected detected commands (tests stage):**

Only **unique** commands survive deduplication. `jest` appears twice (via `test`
and `test:ci`) — only one instance is kept. `jest --ci` is different and is kept.

| Command (as arg list) | Source scripts |
|---|---|
| `["npm", "run", "test"]` | first encountered (`test`) |
| `["npm", "run", "test:coverage"]` | `test:coverage` (`jest --ci` is different from `jest`) |

`test:ci` is deduplicated away because it runs the same underlying command `jest`
as `test`. The deduplication is on the **resolved command** (what npm would run),
not the script name.

**Expected detected commands (lint stage):**

`eslint .` appears twice (via `lint` and `lint:check`) — only one instance is kept.

| Command (as arg list) | Source scripts |
|---|---|
| `["npm", "run", "lint"]` | first encountered (`lint`) |

`lint:check` is deduplicated away because it runs the same underlying command
`eslint .` as `lint`.

> Implementation note: "identical commands" means the argument list that would be
> executed is identical. `npm run test` and `npm run test:ci` both resolve to
> `jest`; one is dropped. `npm run lint` and `npm run lint:check` both resolve to
> `eslint .`; one is dropped.

---

## devdeps-only

**Fixture layout** (relative to `tests/fixtures/devdeps-only/`):

```
package.json    ← JS project with eslint and jest only in devDependencies, no scripts
```

**Expected result:** No commands detected for any stage.
- `eslint` is listed in `devDependencies` but there is no script invoking it and
  no ESLint config file present. **Not project-defined → ignored.**
- `jest` is listed in `devDependencies` but there is no script invoking it and
  no jest config file present. **Not project-defined → ignored.**
- All stages: no commands.
- No `skipped_scripts` (there are no scripts at all).

---

## override-ignore

**Fixture layout** (relative to `tests/fixtures/override-ignore/`):

```
package.json            ← root JS project (tests: jest)
pre-llm.toml            ← ignore = ["legacy"], override for sub/
sub/
  package.json          ← sub JS project (tests: jest, lint: eslint .)
legacy/
  package.json          ← IGNORED by pre-llm.toml ignore rule
```

**`pre-llm.toml` content:**

```toml
ignore = ["legacy"]

[[project]]
path = "sub"
tests = "vitest run"
```

**Expected discovered projects:** 2 (root and `sub`); `legacy/` is skipped.

**Expected detected commands (root project):**

| Stage | Command (as arg list) | Source |
|---|---|---|
| `tests` | `["npm", "run", "test"]` | `script:test` |

**Expected detected commands (`sub` project) — override applied:**

| Stage | Command (as arg list) | Source |
|---|---|---|
| `lint` | `["npm", "run", "lint"]` | `script:lint` |
| `tests` | `["vitest", "run"]` | `override` |

The override **replaces** the detected `npm run test` command for the tests stage
in the `sub` project. Its source is recorded as `"override"`, not `"script:test"`.

**Override path warning:** if `pre-llm.toml` references a path that matches no
project, the tool prints a one-line warning to stderr and continues (not a failure).

**Malformed `pre-llm.toml`:** if the file contains invalid TOML or unknown keys,
print one-line `ERROR:` to stderr and exit 2 (no traceback).

---

## build-gate

**Fixture layout** (relative to `tests/fixtures/build-gate/`):

```
pyproject.toml      ← Python project
pre-llm.toml        ← override: build exits 1, lint/tests/coverage would pass
```

**`pre-llm.toml` overrides:**

| Stage    | Command                              |
|----------|--------------------------------------|
| build    | `python -c "import sys; sys.exit(1)"` |
| lint     | `python -c "print('lint ran')"`       |
| tests    | `python -c "print('tests ran')"`      |
| coverage | `python -c "print('coverage ran')"`   |

**Expected stage results:**

| Stage    | Status    | Reason      |
|----------|-----------|-------------|
| build    | fail      | —           |
| lint     | skipped   | build_gate  |
| tests    | skipped   | build_gate  |
| coverage | skipped   | build_gate  |

**Expected exit code:** 1 (build failed)

**Build gate with `--lint-anyway`:**

| Stage    | Status  | Reason     |
|----------|---------|------------|
| build    | fail    | —          |
| lint     | pass    | —          |
| tests    | skipped | build_gate |
| coverage | skipped | build_gate |

**Build gate with `--steps build,tests` (build excluded from lint, gate still on):**

| Stage | Status  | Reason     |
|-------|---------|------------|
| build | fail    | —          |
| tests | skipped | build_gate |

**Build gate with `--steps lint,tests` (build NOT in steps → gate off):**

| Stage | Status | Reason |
|-------|--------|--------|
| lint  | pass   | —      |
| tests | pass   | —      |

---

## missing-deps

**Fixture layout** (relative to `tests/fixtures/missing-deps/`):

```
pyproject.toml      ← Python project
fake_tests.py       ← prints ModuleNotFoundError and exits 1
pre-llm.toml        ← override: build passes, tests runs fake_tests.py
```

**`pre-llm.toml` overrides:**

| Stage | Command                          |
|-------|----------------------------------|
| build | `python -c "print('build ok')"` |
| tests | `python fake_tests.py`           |

**Expected stage results:**

| Stage    | Status               | Notes                                         |
|----------|----------------------|-----------------------------------------------|
| build    | pass                 | exits 0                                       |
| lint     | no_linter_configured | no lint override, no builtin Python linter    |
| tests    | dependencies_missing | output matched `ModuleNotFoundError` phrase   |
| coverage | skipped              | nothing to run (no coverage override/builtin) |

**Expected warnings:** `dependencies_missing`

**Expected exit code:** 0 (dependencies_missing is a warning, not a failure)

---

## no-linter

**Fixture layout** (relative to `tests/fixtures/no-linter/`):

```
pyproject.toml      ← Python project, no linter config sections
pre-llm.toml        ← overrides for build/tests/coverage but NOT lint
```

**`pre-llm.toml` overrides:**

| Stage    | Command                              |
|----------|--------------------------------------|
| build    | `python -c "print('build ok')"`      |
| tests    | `python -c "print('tests ok')"`      |
| coverage | `python -c "print('coverage ok')"`   |

**Expected stage results:**

| Stage    | Status               | Notes                                   |
|----------|----------------------|-----------------------------------------|
| build    | pass                 | —                                       |
| lint     | no_linter_configured | no lint override, no Python builtin lint |
| tests    | pass                 | —                                       |
| coverage | pass                 | —                                       |

**Expected exit code:** 0 (`no_linter_configured` is not a failure)

---

## nothing-to-run

**Fixture layout** (relative to `tests/fixtures/nothing-to-run/`):

```
pyproject.toml      ← bare Python project, no tools, no scripts, no pre-llm.toml
```

**Expected result:**

- No commands detected for any stage (Python has no builtin phases; no scripts; no config-driven builtins).
- Warning: `nothing_to_run`
- All stages: status `skipped`, reason `nothing_to_run`

**Expected exit code:** 0 (`nothing_to_run` is a warning, not a failure)

---

## independence

**Fixture layout** (relative to `tests/fixtures/independence/`):

```
pre-llm.toml        ← overrides for both sub-projects
proj-pass/
  pyproject.toml    ← Python project; build+tests pass
proj-fail/
  pyproject.toml    ← Python project; tests fail (exit 1)
```

**`pre-llm.toml` overrides:**

| Project   | Stage | Command                                |
|-----------|-------|----------------------------------------|
| proj-pass | build | `python -c "print('build ok')"`        |
| proj-pass | tests | `python -c "print('tests ok')"`        |
| proj-fail | build | `python -c "print('build ok')"`        |
| proj-fail | tests | `python -c "import sys; sys.exit(1)"` |

**Expected stage results for `proj-pass`:**

| Stage    | Status               |
|----------|----------------------|
| build    | pass                 |
| lint     | no_linter_configured |
| tests    | pass                 |
| coverage | skipped              |

**Expected stage results for `proj-fail`:**

| Stage    | Status               |
|----------|----------------------|
| build    | pass                 |
| lint     | no_linter_configured |
| tests    | fail                 |
| coverage | skipped              |

**Key assertion:** `proj-pass` completes all its stages regardless of `proj-fail`'s outcome.
`proj-fail` does not affect `proj-pass` in any way (projects are independent).

**Expected exit code:** 1 (`proj-fail` has a test failure)


---

## terminal-table

Session 9. Not a folder fixture: `tests/test_output.py` builds these three projects in memory and
compares `render_terminal(...)` to the block below, character for character
(`python`/`go` are untested; `javascript` is tested).

| Project | Build | Lint | Tests | Coverage |
|---|---|---|---|---|
| `backend` (python) | pass | no_linter_configured | fail (`pytest -q`) | pass, lowest line 72.0 |
| `web` (javascript) | fail (`npm run build`) | skipped (build_gate) | skipped | skipped |
| `services/worker` (go) | pass | pass | pass | pass, but no coverage data (`coverage_missing`) |

**Cell words:** `PASS`, `FAIL`, `TIMEOUT`, `INTR` (interrupted), `WARN` (no_linter_configured,
dependencies_missing, tool_not_installed, or coverage without data), `SKIP` (did not run).
Worst wins: INTR > FAIL > TIMEOUT > WARN > PASS > SKIP. A passing coverage stage with data shows
the lowest line percentage, e.g. `72.0%`. Columns are left-aligned, two spaces apart, trailing
spaces trimmed. A `[untested]` suffix goes on the language.

**Expected output:**

```
Project          Language           Build  Lint  Tests  Coverage
---------------  -----------------  -----  ----  -----  --------
backend          python [untested]  PASS   WARN  FAIL   72.0%
web              javascript         FAIL   SKIP  SKIP   SKIP
services/worker  go [untested]      PASS   PASS  PASS   WARN

Details:
  backend / lint: WARN  no linter configured
  backend / tests: FAIL  pytest -q  (log: .pre-llm/logs/backend/tests-0.log)
  web / build: FAIL  npm run build  (log: .pre-llm/logs/web/build-0.log)
  services/worker / coverage: WARN  no coverage data

Warnings:
  services/worker: coverage_missing

Summary: 3 projects: 0 passed, 1 with warnings, 2 failed
```

Rules shown: the Details section lists only FAIL / TIMEOUT / INTR / WARN cells (never PASS or SKIP),
in project order then stage order; the Warnings section lists project-level warnings; sections with
nothing to show are left out (including their blank line). A run with every cell PASS prints only
the table, a blank line, and the Summary.

**Exit codes** (`compute_exit_code`): 0 all passed or only warnings; 1 any fail or timeout;
130 interrupted (wins over everything); 3 no projects.

**Environment block** (report key `environment`): `{"os": "<system> <release>", "runners": {"<name>": "<first line of --version>" | "unknown"}}`.
Runners are the executables of commands that actually ran (not skipped), one entry per name.

---

## python-* (Session 10)

Tiny stdlib-only Python projects. They need no installed packages: tests are `python -B -m unittest -q`,
the "linter" is `python -B lint_check.py` (every `*.py` in the folder must parse), declared in each
fixture's `pre-llm.toml`. `-B` keeps the fixture folder free of `__pycache__`. Python has **no build
command**, so the Build cell is always `SKIP`. No fixture configures coverage, so Coverage is `SKIP`.
Run each with `--path tests/fixtures/<name>`; the project is `.`, language `python [untested]`.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `python-ok` | SKIP | PASS | PASS | SKIP | 0 | |
| `python-test-fail` | SKIP | PASS | FAIL | SKIP | 1 | `add(2, 3) == 6` is asserted; Details lists `. / tests: FAIL` |
| `python-lint-fail` | SKIP | FAIL | PASS | SKIP | 1 | `bad_syntax.py` does not parse; tests still run (lint failure does not gate tests) |
| `python-no-tests` | SKIP | PASS | SKIP | SKIP | 0 | no tests command, no test config: the tests stage is skipped (`nothing_to_run`), no project warning |
| `python-no-linter` | SKIP | WARN | PASS | SKIP | 0 | no lint command, no lint config: `no_linter_configured`; Details says `no linter configured` |

Report checks: `projects[0].commands` has one entry per stage; lint on `python-no-linter` has
`status: "no_linter_configured"`; `python-lint-fail` lint entry has `status: "fail"` and a non-empty `output_tail`
naming `bad_syntax.py`.

### python-detect

No `pre-llm.toml`. `pyproject.toml` declares `[tool.pytest.ini_options]`, `[tool.ruff]` and
`[tool.coverage.run]`. Nothing is installed or run: check it with `--dry-run`. Expected lines
(after the project line, which shows the full path, `python`, `pyproject.toml` and `[untested]`):

```
  lint: ruff check .  [config]
  tests: pytest  [config]
  coverage: pytest --cov --cov-report=xml  [config]
```

Python has no `build` line. A `pyproject.toml` that lists `pytest` or `ruff` only as a dependency
(and has no `[tool.*]` table) detects nothing.

---

## js-* (Session 11)

Tiny JavaScript projects that need **no `npm install`**: they use only Node built-ins. Scripts in each
`package.json`: `build` = `node --check calc.js` (syntax check), `lint` = `node lint-check.js`
(fails on a `debugger` statement), `test` = `node --test`. Requires `node` and `npm` on PATH.

JavaScript projects are skipped as `dependencies_missing` when `node_modules` does not exist, and this
repo does not commit `node_modules`. **Create an empty `node_modules` folder in a copy of the fixture
before running** (`tests/manual_js_check.py` does this). Run with `--path <copy>`; the project is `.`,
language `javascript [untested]`. No fixture configures coverage, so Coverage is `SKIP`.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `js-ok` | PASS | PASS | PASS | SKIP | 0 | |
| `js-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | `calc.js` has a syntax error; build gate skips the rest (`build_gate`) |
| `js-test-fail` | PASS | PASS | FAIL | SKIP | 1 | asserts `add(2, 3) === 6` |
| `js-lint-fail` | PASS | FAIL | PASS | SKIP | 1 | `debugger;` in `calc.js`; lint output names `calc.js:2: no-debugger`; tests still run |
| `js-no-tests` | PASS | PASS | SKIP | SKIP | 0 | no `test` script, no test config: tests stage skipped (`nothing_to_run`) |
| `js-no-linter` | PASS | WARN | PASS | SKIP | 0 | no `lint` script, no lint config: `no_linter_configured` |

Report checks: `js-no-linter` lint entry has `status: "no_linter_configured"`; `js-build-fail` build entry is `fail`
and its lint/tests/coverage entries have `reason: "build_gate"`; `js-lint-fail` lint `output_tail` names `calc.js`.

### js-detect

No scripts. `package.json` is bare; `eslint.config.js`, `jest.config.js` and `tsconfig.json` declare the tools.
Nothing is installed or run: check with `--dry-run`. Expected lines after the project line (they go through
`npx --no-install`, so nothing is ever downloaded):

```
  build: npx --no-install tsc --noEmit  [config]
  lint: npx --no-install eslint .  [config]
  tests: npx --no-install jest  [config]
  coverage: npx --no-install jest --coverage --coverageReporters=json-summary  [config]
```

A `package.json` that lists `eslint`, `jest` or `typescript` only under `devDependencies` detects nothing
(see `devdeps-only`).

TypeScript note: TS projects are the same `javascript` language entry. `tsconfig.json` is detected as a
build (type-check) command; there is no separate TS fixture yet.

---

## java-* (Session 12)

Tiny Java projects that need **no Maven, Gradle or network**: each has a bare `pom.xml` (it makes the folder a
Java project) and a `pre-llm.toml` that replaces the build tool with the JDK:
`build` = `javac -d out Calc.java CalcTest.java`, `tests` = `java -cp out CalcTest`,
`lint` = `java LintCheck.java` (fails on a `FIXME` marker). Requires `javac` and `java` (JDK 11+) on PATH.
`out/` is ignored by a `.gitignore` in each fixture. Run with `--path <copy>`; the project is `.`,
language `java [untested]`. No fixture configures coverage, so Coverage is `SKIP`.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `java-ok` | PASS | PASS | PASS | SKIP | 0 | |
| `java-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | `Calc.java` does not compile; build gate skips the rest (`build_gate`) |
| `java-test-fail` | PASS | PASS | FAIL | SKIP | 1 | asserts `add(2, 3) == 6` |
| `java-lint-fail` | PASS | FAIL | PASS | SKIP | 1 | `// FIXME` in `Calc.java`; lint output names `Calc.java:3: no-fixme`; tests still run |
| `java-no-linter` | PASS | WARN | PASS | SKIP | 0 | bare `pom.xml`, no checkstyle/pmd/spotbugs plugin, no lint config: `no_linter_configured` |

**No `java-no-tests` fixture (n/a for Java).** Maven and Gradle have a built-in `test` phase, so a Java project
always has a tests command (`mvn test` / `gradle test`); a project with zero tests is a successful run decided
by the build tool, not by this tool. Checklist cell: `n/a`.

### java-maven-detect and java-gradle-detect

Real build files, no `pre-llm.toml`. Checked with `--dry-run`; nothing is installed or run. Built-in
phases (`build`, `tests`) come from the project's own build tool; **lint and coverage appear only because the
build file declares the plugin** (a bare `pom.xml` / `build.gradle` has neither; see `java-no-linter`).
Expected lines after the project line:

`java-maven-detect` (pom.xml declares `maven-checkstyle-plugin` and `jacoco-maven-plugin`):
```
  build: mvn compile  [builtin]
  lint: mvn checkstyle:check  [config]
  tests: mvn test  [builtin]
  coverage: mvn jacoco:report  [config]
```

`java-gradle-detect` (build.gradle declares `checkstyle` and `jacoco`):
```
  build: gradle build  [builtin]
  lint: gradle checkstyleMain  [config]
  tests: gradle test  [builtin]
  coverage: gradle jacocoTestReport  [config]
```

A Maven project never lists `gradle ...` commands and a Gradle project never lists `mvn ...` commands.
The wrapper (`mvnw` / `gradlew`) is chosen by the runner at run time, so `--dry-run` shows plain `mvn` / `gradle`.

**Not covered by fixtures:** a real `mvn` / `gradle` run (needs the tools and network). Try one by hand on a
real Maven or Gradle project before marking Java `tested`.

**Shared Gradle build files.** `build.gradle` / `build.gradle.kts` are claimed by both `java` and `kotlin`. A folder
with one of them is reported **once**: for the language whose source extensions (`.java` / `.kt`) exist under it
(both languages if both exist; `.gradle` / `.gradle.kts` scripts never count as sources); with no sources at all,
the first declared language (`java`). So `java-gradle-detect` (no sources) lists only Java commands.

---

## kotlin-* (Session 13)

Kotlin builds with Gradle, and a Kotlin compiler or a Gradle download cannot be assumed on every machine, so there are
**no execution fixtures for Kotlin** (the generic ok / build-fail / test-fail / lint-fail behaviour is already covered
by the Python, JavaScript and Java fixtures, which share the same runner). Kotlin-specific behaviour is detection,
checked with `--dry-run`:

### kotlin-detect

`build.gradle.kts` applies the Kotlin JVM, detekt and jacoco plugins; `src/main/kotlin/Main.kt` makes it a Kotlin
project (see "Shared Gradle build files" under java-*). Expected lines after the project line (language `kotlin`):

```
  build: gradle build  [builtin]
  lint: gradle detekt  [config]
  tests: gradle test  [builtin]
  coverage: gradle jacocoTestReport  [config]
```

A bare Kotlin `build.gradle(.kts)` lists only `build: gradle build` and `tests: gradle test`: lint and coverage run
only when the build file declares detekt / ktlint / jacoco (or a `detekt.yml` sits next to it). The previous
built-in `gradle check` (which also runs tests) is gone. A Kotlin project never lists `mvn ...` commands.

**Not covered by fixtures:** a real Gradle run. Try one by hand before marking Kotlin `tested`.

---

## go-* (Session 14)

Tiny Go modules, standard library only (no downloads). Commands are the Go toolchain's own built-ins:
`go build ./...`, `go vet ./...`, `go test ./...`, `go test -coverprofile=coverage.out ./...`. Requires `go` (1.18+) on
PATH. `coverage.out` is written into the project folder and ignored by each fixture's `.gitignore`. Run with
`--path <copy>`; the project is `.`, language `go [untested]`.

The Coverage cell is the lowest line percentage from `coverage.out`, a **Go cover profile** (statement coverage; it is
not lcov and has no branch data).

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `go-ok` | PASS | PASS | PASS | 100.0% | 0 | |
| `go-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | syntax error; build gate skips the rest (`build_gate`) |
| `go-test-fail` | PASS | PASS | FAIL | FAIL | 1 | asserts `Add(2, 3) == 6`; the coverage command runs the tests again, so it fails too |
| `go-lint-fail` | PASS | FAIL | PASS | 100.0% | 1 | `go vet` (copylocks) rejects `Show(c Counter)`; `go test` does not run that check, so tests still pass |

**Not applicable for Go:**
- *no-linter*: `go vet` ships with the toolchain, so every Go module has a linter (a `.golangci.yml` replaces it, see
  go-detect).
- *no-tests*: `go test ./...` on a module without tests succeeds (`[no test files]`) and what the profile contains
  depends on the Go version, so the result is decided by the toolchain, not this tool.

### go-detect

`go.mod` plus `.golangci.yml`. Checked with `--dry-run`. Expected lines after the project line:

```
  build: go build ./...  [builtin]
  lint: golangci-lint run  [config]
  tests: go test ./...  [builtin]
  coverage: go test -coverprofile=coverage.out ./...  [builtin]
```

Without `.golangci.yml` the lint line is `lint: go vet ./...  [builtin]`.

**Not verified by the author:** `go` is not installed on the machine these fixtures were written on; the Go sources and
the expected cells are derived from the Go toolchain's documented behaviour. If a cell differs on your machine, that is a
fixture bug to report.

---

## csharp-* (Session 15)

C#/.NET projects need the .NET SDK, a target framework that matches the installed SDK, and NuGet restore, none of
which can be assumed, so there are **no execution fixtures for C#** (the generic ok / build-fail / test-fail / lint-fail
behaviour is covered by the other languages' fixtures through the same runner). C#-specific behaviour is detection and
the coverage file location, checked by `tests/test_detection_csharp.py` and `--dry-run`.

### csharp-detect

`App.Tests.csproj` references `coverlet.collector`. Expected lines after the project line (language `csharp`):

```
  build: dotnet build  [builtin]
  lint: dotnet format --verify-no-changes  [builtin]
  tests: dotnet test  [builtin]
  coverage: dotnet test --collect:XPlat Code Coverage  [config]
```

(the last argument is a single argument, `--collect:XPlat Code Coverage`; `--dry-run` joins arguments with spaces.)

Rules shown:
- `dotnet format --verify-no-changes` is read-only and ships with the SDK, so every .NET project has a linter
  (*no-linter* is n/a).
- Coverage is **not** built-in. It runs only when the project file references `coverlet.collector` or a `*.runsettings`
  file sits next to it. A project without either has no coverage command (Coverage cell `SKIP`).
- `.sln` wins over `.csproj` when both exist (both stay in `build_files`).
- Coverage is read from `**/TestResults/*/coverage.cobertura.xml` (that is where `dotnet test` writes it, inside the test
  project folder, in a fresh GUID folder per run); files from earlier runs are stale by mtime and ignored.

**Not covered by fixtures:** a real `dotnet build` / `dotnet test` run. Try one by hand before marking C# `tested`.

---

## rust-* (Session 16)

Tiny crates with no dependencies (no downloads). Commands are the Cargo toolchain's built-ins: `cargo build`,
`cargo clippy`, `cargo test`. Requires `cargo` with the `clippy` component (`rustup component add clippy`) on PATH.
`target/` and `Cargo.lock` are ignored by each fixture's `.gitignore`. Run with `--path <copy>`; the project is `.`,
language `rust [untested]`. No fixture configures coverage, so Coverage is `SKIP`.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `rust-ok` | PASS | PASS | PASS | SKIP | 0 | |
| `rust-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | syntax error; build gate skips the rest (`build_gate`). Must **not** be reported as `dependencies_missing` |
| `rust-test-fail` | PASS | PASS | FAIL | SKIP | 1 | asserts `add(2, 3) == 6` |
| `rust-lint-fail` | PASS | FAIL | PASS | SKIP | 1 | `#![deny(clippy::needless_return)]` plus `return a + b;`: clippy errors, rustc and `cargo test` do not run it |

**Not applicable for Rust:**
- *no-linter*: `cargo clippy` ships with the toolchain, so every crate has a linter.
- *no-tests*: `cargo test` on a crate without tests succeeds, which is decided by the toolchain.

### rust-detect

`Cargo.toml` with a `[package.metadata.tarpaulin]` table. Checked with `--dry-run`. Expected lines after the project line:

```
  build: cargo build  [builtin]
  lint: cargo clippy  [builtin]
  tests: cargo test  [builtin]
  coverage: cargo tarpaulin --out Xml  [config]
```

Coverage is **not** built-in. `cargo tarpaulin` is a separate install, so it runs only when the crate declares it
(`tarpaulin.toml`, `.tarpaulin.toml`, or a `[package.metadata.tarpaulin]` table). A crate without any of them has no
coverage command. tarpaulin's `--out Xml` writes `cobertura.xml`, which the Cobertura reader parses.

**Dependency detection.** `dep_error_phrases` for Rust are `no matching package`, `failed to select a version`,
`failed to download`, ``failed to get ` ``. The earlier `could not compile` and `error[E` appear for *every* rustc error
and would have reported real build failures as `dependencies_missing`.

**Not verified by the author:** `cargo` is not installed on the machine these fixtures were written on; the sources and
expected cells follow the toolchain's documented behaviour. If a cell differs on your machine, that is a fixture bug.
