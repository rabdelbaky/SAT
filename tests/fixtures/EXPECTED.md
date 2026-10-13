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

**Expected projects** (5 total, ordered by path):

| Path (relative to fixture root) | Language   | Primary build file   | All build_files                           | tested   |
|---------------------------------|------------|----------------------|-------------------------------------------|----------|
| `.`                             | javascript | `package.json`       | `["package.json"]`                        | true     |
| `packages/api`                  | javascript | `package.json`       | `["package.json"]`                        | true     |
| `packages/ui`                   | javascript | `package.json`       | `["package.json"]`                        | true     |
| `services/ml`                   | python     | `pyproject.toml`     | `["pyproject.toml", "requirements.txt"]`  | true     |
| `services/worker`               | go         | `go.mod`             | `["go.mod"]`                              | true     |

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

**--dry-run output** (one line per project, format: `<path>  <language>  <build_files>  [untested]`;
the `[untested]` suffix is left off for a tested language):

```
.  javascript  package.json
packages/api  javascript  package.json
packages/ui  javascript  package.json
services/ml  python  pyproject.toml, requirements.txt
services/worker  go  go.mod
```

*(Python is tested since Session 10, JavaScript since Session 11, Java since Session 12, Kotlin and Go since Session 14,
C# since Session 15, Ruby since Session 18; the others are `[untested]` until their fixtures pass; exact whitespace may vary.)*

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
(the in-memory projects set `tested` themselves: `backend` (python) and `services/worker` (go) are built as untested
to show the `[untested]` label, `web` (javascript) as tested; this is not read from languages.toml, where all three are
tested).

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

Tiny Python projects. The "linter" is `python -B lint_check.py` (every `*.py` in the folder must
parse), declared in each fixture's `pre-llm.toml`. `python-ok` and `python-test-fail` run tests with
the detected `pytest` (from `[tool.pytest.ini_options]` in their `pyproject.toml`, with
`addopts = "-q -p no:cacheprovider"`), so they need `pytest` on PATH. The other run fixtures still
use `python -B -m unittest -q` from `pre-llm.toml` and need no installed packages. `-B` keeps the
fixture folder free of `__pycache__`. Python has **no build
command**, so the Build cell is always `SKIP`. No fixture configures coverage, so Coverage is `SKIP`.
Run each with `--path tests/fixtures/<name>`; the project is `.`, language `python` (tested, so no
`[untested]` label).

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `python-ok` | SKIP | PASS | PASS | SKIP | 0 | |
| `python-test-fail` | SKIP | PASS | FAIL | SKIP | 1 | `add(2, 3) == 6` is asserted; Details lists `. / tests: FAIL` |
| `python-lint-fail` | SKIP | FAIL | PASS | SKIP | 1 | `bad_syntax.py` does not parse; tests still run (lint failure does not gate tests) |
| `python-no-tests` | SKIP | PASS | SKIP | SKIP | 0 | no tests command, no test config: the tests stage is skipped (`nothing_to_run`), no project warning |
| `python-no-linter` | SKIP | WARN | PASS | SKIP | 0 | no lint command, no lint config: `no_linter_configured`; Details says `no linter configured` |

Report checks: `projects[0].commands` has one entry per stage; lint on `python-no-linter` has
`status: "no_linter_configured"`; `python-lint-fail` lint entry has `status: "fail"` and a non-empty `output_tail`
naming `bad_syntax.py`. On `python-ok` and `python-test-fail` the tests entry has `"command": ["pytest"]`
and `"source": "config"`.

### python-detect

No `pre-llm.toml`. `pyproject.toml` declares `[tool.pytest.ini_options]`, `[tool.ruff]` and
`[tool.coverage.run]`. Nothing is installed or run: check it with `--dry-run`. Expected lines
(after the project line, which shows the full path, `python` and `pyproject.toml`):

```
  lint: ruff check .  [config]
  tests: pytest  [config]
  coverage: pytest --cov --cov-report=xml  [config]
```

Python has no `build` line. A `pyproject.toml` that lists `pytest` or `ruff` only as a dependency
(and has no `[tool.*]` table) detects nothing.

### python-detect-ini

No `pyproject.toml` and no `pre-llm.toml`; the build file is `requirements.txt`. `setup.cfg` declares
`[tool:pytest]`, `[flake8]` and `[coverage:run]`. Nothing is installed or run: check it with
`--dry-run`. Expected lines (after the project line, which shows the full path, `python` and
`requirements.txt`), exactly these and no `build` line:

```
  lint: flake8 .  [config]
  tests: pytest  [config]
  coverage: pytest --cov --cov-report=xml  [config]
```

---

## js-* (Session 11)

Tiny JavaScript projects that need **no `npm install`**: they use only Node built-ins. Scripts in each
`package.json`: `build` = `node --check calc.js` (syntax check), `lint` = `node lint-check.js`
(fails on a `debugger` statement), `test` = `node --test`. Requires `node` and `npm` on PATH.

The fixtures declare no packages (no `dependencies` / `devDependencies` / `optionalDependencies` /
`peerDependencies`), so the `node_modules` check does not apply and no `node_modules` folder is needed.
Only `js-missing-deps` declares a package. Run with `--path tests/fixtures/<name>` (or a copy); the
project is `.`, language `javascript` (tested since Session 11, so no `[untested]` label). No fixture configures coverage, so Coverage is `SKIP`.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `js-ok` | PASS | PASS | PASS | SKIP | 0 | |
| `js-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | `calc.js` has a syntax error; build gate skips the rest (`build_gate`) |
| `js-test-fail` | PASS | PASS | FAIL | SKIP | 1 | asserts `add(2, 3) === 6` |
| `js-lint-fail` | PASS | FAIL | PASS | SKIP | 1 | `debugger;` in `calc.js`; lint output names `calc.js:2: no-debugger`; tests still run |
| `js-no-tests` | PASS | PASS | SKIP | SKIP | 0 | no `test` script, no test config: tests stage skipped (`nothing_to_run`) |
| `js-no-linter` | PASS | WARN | PASS | SKIP | 0 | no `lint` script, no lint config: `no_linter_configured` |
| `js-bad-require` | PASS | PASS | FAIL | SKIP | 1 | test requires `./calcx.js`, which does not exist: a code bug, so FAIL, not a warning |
| `js-missing-deps` | SKIP | SKIP | SKIP | SKIP | 0 | declares `left-pad`, no `node_modules`: every stage skipped, warning `dependencies_missing` |
| `js-missing-deps` + empty `node_modules` | PASS | WARN | WARN | SKIP | 0 | half-done install: test prints `Cannot find module 'left-pad'` -> `dependencies_missing` |

Report checks: `js-no-linter` lint entry has `status: "no_linter_configured"`; `js-build-fail` build entry is `fail`
and its lint/tests/coverage entries have `reason: "build_gate"`; `js-lint-fail` lint `output_tail` names `calc.js`.
`js-bad-require` tests entry has `status: "fail"` and its `output_tail` names `calcx`. `js-missing-deps` (no
`node_modules`): the build, lint, tests and coverage entries each have a `reason` starting with
`dependencies_missing`, and the project's `warnings` list contains `dependencies_missing`. `js-missing-deps` with an
empty `node_modules`: tests entry has `status: "dependencies_missing"` and its `output_tail` names `left-pad`.

### ts-ok, ts-build-fail

TypeScript through the detected config rule: no scripts, `package.json` is bare, and `tsconfig.json` gives the
build command `npx --no-install tsc --noEmit` (`source: "config"`). Needs `tsc` on PATH
(`npm install -g typescript`). `tsc --noEmit` writes no files.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `ts-ok` | PASS | WARN | SKIP | SKIP | 0 | no linter, no tests configured |
| `ts-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | `TS2322` in the build `output_tail` |

Report checks: `ts-ok` build entry has `"command": ["npx", "--no-install", "tsc", "--noEmit"]`,
`"source": "config"` and `status: "pass"`; `ts-build-fail` build entry has `status: "fail"` and `TS2322` in its
`output_tail`.

Without `tsc` installed, Build shows `WARN` (`dependencies_missing`: "npx canceled due to missing packages"),
never `FAIL`.

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

TypeScript note: TS projects are the same `javascript` language entry. `ts-ok` and `ts-build-fail` run the
`tsconfig.json` rule for real. A `jest` or `mocha` key in `package.json` declares that tool just like its
config file does. A `typecheck` / `type-check` script is a build command.

---

## java-* (Session 12)

Tiny Java projects that need **no Maven, Gradle or network**: each has a bare `pom.xml` (it makes the folder a
Java project) and a `pre-llm.toml` that replaces the build tool with the JDK:
`build` = `javac -d out Calc.java CalcTest.java`, `tests` = `java -cp out CalcTest`,
`lint` = `java LintCheck.java` (fails on a `FIXME` marker). Requires `javac` and `java` (JDK 17+) on PATH.
`out/` is ignored by a `.gitignore` in each fixture. Run with `--path <copy>`; the project is `.`,
language `java` (tested since Session 12, so no `[untested]` label). No fixture configures coverage, so Coverage is `SKIP`.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `java-ok` | PASS | PASS | PASS | SKIP | 0 | |
| `java-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | `Calc.java` does not compile; build gate skips the rest (`build_gate`) |
| `java-test-fail` | PASS | PASS | FAIL | SKIP | 1 | asserts `add(2, 3) == 6` |
| `java-lint-fail` | PASS | FAIL | PASS | SKIP | 1 | `// FIXME` in `Calc.java`; lint output names `Calc.java:3: no-fixme`; tests still run |
| `java-no-linter` | PASS | WARN | PASS | SKIP | 0 | bare `pom.xml`, no checkstyle/pmd/spotbugs plugin, no lint config: `no_linter_configured` |

### Real Maven and Gradle runs

These run the real build tools. Requires `mvn` and `gradle` on PATH, a JDK 17 or newer, and internet access the
first time (Maven and Gradle download the fixture's plugins and libraries into their own cache; this tool
installs nothing). If `gradle` is not on PATH, `tests/manual_java_check.py` shows the Gradle rows as `SKIP` (not run) and
counts them separately; they never count as passed. `java-maven-ok` and `java-gradle-ok` are the same tiny project (`demo.Calc` with `add` and
`sub`, one JUnit 5 test for `add`) built by Maven or Gradle. Both declare checkstyle (one rule from
`checkstyle.xml`: no `FIXME` comments) and JaCoCo (Gradle with `xml.required = true`). Coverage is
1 of 3 lines (`add`; `sub` and the class line are not run) = `33.3%`.

The other rows are **variants** that `tests/manual_java_check.py` makes in a temp copy of the `-ok` fixture:
- `build-fail`: in `Calc.java`, `return a + b;` becomes `return a + ;`
- `test-fail`: in `CalcTest.java`, `assertEquals(5,` becomes `assertEquals(6,`
- `lint-fail`: a `// FIXME check overflow` line is added above `sub` in `Calc.java`
- `no-tests`: the `src/test` folder is deleted

| Run | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `java-maven-ok` | PASS | PASS | PASS | 33.3% | 0 | build `mvn compile`; coverage from `target/site/jacoco/jacoco.xml` |
| `java-maven-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | a compile error is `fail`, never `dependencies_missing` |
| `java-maven-test-fail` | PASS | PASS | FAIL | 33.3% | 1 | tests output names `CalcTest` |
| `java-maven-lint-fail` | PASS | FAIL | PASS | 33.3% | 1 | `mvn checkstyle:check` output names `Calc.java` |
| `java-maven-no-tests` | PASS | PASS | SKIP | WARN | 0 | `No tests to run.`: tests `skipped`, reason `no_tests_found`; no coverage data |
| `java-maven-multi` | PASS | WARN | PASS | SKIP | 0 | one project (see below); `lib` has no tests, `app` has one |
| `java-gradle-ok` | PASS | PASS | PASS | 33.3% | 0 | build `gradle assemble`; coverage from `build/reports/jacoco/test/jacocoTestReport.xml` |
| `java-gradle-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | |
| `java-gradle-test-fail` | PASS | PASS | FAIL | 33.3% | 1 | the build stage does not run tests, so a test failure shows under Tests |
| `java-gradle-lint-fail` | PASS | FAIL | PASS | 33.3% | 1 | `gradle checkstyleMain` output names `Calc.java` |
| `java-gradle-no-tests` | PASS | PASS | SKIP | WARN | 0 | `> Task :test NO-SOURCE`: tests `skipped`, reason `no_tests_found` |
| `java-gradle-multi` | PASS | WARN | PASS | SKIP | 0 | one project (see below) |

**No tests.** A Java project always has a tests command (`mvn test` / `gradle test`). When it passes but ran no
test (languages.toml `no_tests_patterns` match the full log and `tests_ran_patterns` do not), the Tests cell is
`SKIP` and the report entry is `status: skipped`, `reason: no_tests_found`, not a `PASS` with nothing behind it.

**Multi-module.** `java-maven-multi` (root `pom.xml` lists modules `lib` and `app`; `app` depends on `lib`) and
`java-gradle-multi` (`settings.gradle` includes `lib` and `app`) are reported as **one** project `.`: a Maven module
or Gradle subproject is built by the root build (languages.toml `subproject_rules`). Built on its own, `app`
would show a false `dependencies_missing` because `lib` is only on its classpath inside the root build.

### java-maven-wrapper and java-gradle-wrapper

A bare build file plus fake wrapper scripts that only print one line (no Maven or Gradle needed): `mvnw` /
`mvnw.cmd` print `fixture mvnw (sh) <args>` / `fixture mvnw.cmd <args>`; `gradlew` / `gradlew.bat` print
`fixture gradlew (sh) <args>` / `fixture gradlew.bat <args>`. The `.sh` scripts are committed **without** the
executable bit, so on macOS/Linux they run as `sh mvnw`.

| Fixture | Build | Lint | Tests | Coverage | Exit |
|---|---|---|---|---|---|
| `java-maven-wrapper` | PASS | WARN | PASS | SKIP | 0 |
| `java-gradle-wrapper` | PASS | WARN | PASS | SKIP | 0 |

Report: the build entry's `command` names the wrapper that ran, not a path: `["mvnw.cmd", "compile"]` /
`["gradlew.bat", "assemble"]` on Windows, `["mvnw", "compile"]` / `["gradlew", "assemble"]` elsewhere, and its
output has the matching `fixture ...` line. `environment.runners` has the wrapper as `unknown` and no `mvn` /
`gradle` entry (the tool on PATH did not run). On Windows only `mvnw.cmd` / `gradlew.bat` (or `gradlew.cmd`)
are used; without one, the tool on PATH is used.

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
  build: gradle assemble  [builtin]
  lint: gradle checkstyleMain  [config]
  tests: gradle test  [builtin]
  coverage: gradle jacocoTestReport  [config]
```

A Maven project never lists `gradle ...` commands and a Gradle project never lists `mvn ...` commands.
The wrapper (`mvnw` / `gradlew`) is chosen by the runner at run time, so `--dry-run` shows plain `mvn` / `gradle`.
Gradle's build command is `assemble`, not `build`: `gradle build` also runs `test` and `check`, so a failing test
or lint would show as a Build failure and the build gate would hide it.

A plugin counts only when the build file really declares it: text inside comments (`<!-- -->` in `pom.xml`,
`//` and `/* */` in Gradle scripts) is ignored. A lone `checkstyle.xml` / `pmd.xml` next to `pom.xml` adds
nothing: Maven ignores it unless the plugin in `pom.xml` points to it.

**Shared Gradle build files.** `build.gradle` / `build.gradle.kts` are claimed by both `java` and `kotlin`. A folder
with one of them is reported **once**: for the language whose source extensions (`.java` / `.kt`) exist under it
(both languages if both exist; `.gradle` / `.gradle.kts` scripts never count as sources); with no sources at all,
the first declared language (`java`). So `java-gradle-detect` (no sources) lists only Java commands.

---

## kotlin-* (Session 13)

Kotlin builds with Gradle only. The fixtures are checked by `tests/manual_lang_check.py kotlin`; every fixture is
copied to a temp folder and run with `--path <copy>`; the project is `.`, language `kotlin` (tested since Session 14, so no
`[untested]` label).

### Real Gradle runs

These run real Gradle. Requires `gradle` on PATH, a JDK, and internet access the first time (Gradle downloads the
Kotlin, detekt and JaCoCo plugins and the libraries into its own cache; this tool installs nothing). If `gradle` is not
on PATH, `tests/manual_lang_check.py` shows every real-Gradle check as `SKIP` (not run: gradle is not on PATH) and
ends with `All checks passed: N/N (M Gradle checks not run: gradle is not on PATH)`; a `SKIP` never counts as
passed.

`kotlin-gradle-ok` is a tiny project: `settings.gradle.kts`, `build.gradle.kts` with the Kotlin JVM plugin
(`2.0.21`), detekt (`io.gitlab.arturbosch.detekt` `1.23.8`, default rules) and `jacoco` (XML report on), no
`jvmToolchain` (it would make Gradle download a JDK); `demo.Calc` (an `object` with `add`, `sub`, `mul`) and one
`kotlin.test` test, `assertEquals(5, Calc.add(2, 3))`. `build/` and `.gradle/` are in its `.gitignore`.

The other `-ok` rows are **variants** that `tests/manual_lang_check.py` makes in a temp copy of `kotlin-gradle-ok`:
- `build-fail`: in `Calc.kt`, `a + b` becomes `a +`
- `test-fail`: in `CalcTest.kt`, `assertEquals(5,` becomes `assertEquals(6,`
- `lint-fail`: a `// FIXME: check overflow` line is added above `fun sub` in `Calc.kt` (detekt's default
  `ForbiddenComment` rule flags it)
- `no-tests`: the `src/test` folder is deleted
- `no-linter`: the detekt plugin line is removed from `build.gradle.kts`

`<percent>` means any coverage percentage: the check only looks for a cell ending in `%`, read from
`build/reports/jacoco/test/jacocoTestReport.xml` (the report's coverage `source_file`).

| Run | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `kotlin-gradle-ok` | PASS | PASS | PASS | `<percent>` | 0 | build `gradle assemble` (report `command` `["gradle", "assemble"]`); lint `gradle detekt` |
| `kotlin-gradle-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | build `fail`, never `dependencies_missing`; lint/tests reason `build_gate` |
| `kotlin-gradle-test-fail` | PASS | PASS | FAIL | `<percent>` | 1 | the build stage does not run tests; tests output names `CalcTest` |
| `kotlin-gradle-lint-fail` | PASS | FAIL | PASS | `<percent>` | 1 | `gradle detekt` output names `Calc.kt`; tests still run |
| `kotlin-gradle-no-tests` | PASS | PASS | SKIP | WARN | 0 | `> Task :test NO-SOURCE`: tests `skipped`, reason `no_tests_found`; no coverage data |
| `kotlin-gradle-no-linter` | PASS | WARN | PASS | `<percent>` | 0 | no detekt / ktlint plugin: lint `no_linter_configured` |
| `kotlin-gradle-multi` | PASS | WARN | PASS | SKIP | 0 | exactly **one** table row and one report project (see below) |

**Multi-project.** `kotlin-gradle-multi` has `settings.gradle.kts` with `include("app", "lib")`, a root
`build.gradle.kts` that declares the Kotlin plugin (`apply false`) and applies it to every subproject, and `app`
depends on `project(":lib")`; `lib` has no tests, `app` has one. It is reported as **one** project `.`: a Gradle
subproject is built by the root build (languages.toml `subproject_rules`), so it is not built again on its own.

### kotlin-gradle-wrapper

A `build.gradle.kts` (`plugins { kotlin("jvm") }`), `src/main/kotlin/Main.kt`, and fake `gradlew` / `gradlew.bat`
copied from `java-gradle-wrapper` that only print `fixture gradlew (sh) <args>` / `fixture gradlew.bat <args>`.
Needs no Gradle.

| Fixture | Build | Lint | Tests | Coverage | Exit |
|---|---|---|---|---|---|
| `kotlin-gradle-wrapper` | PASS | WARN | PASS | SKIP | 0 |

Report: the build entry's `command` is `["gradlew.bat", "assemble"]` on Windows, `["gradlew", "assemble"]`
elsewhere, and its output has the matching `fixture ...` line. `environment.runners` has `gradlew` = `unknown` and
no `gradle` entry.

### kotlin-detect

`build.gradle.kts` applies the Kotlin JVM, detekt and jacoco plugins; `src/main/kotlin/Main.kt` makes it a Kotlin
project (see "Shared Gradle build files" under java-*). Checked with `--dry-run`; nothing is run. Expected lines after
the project line (language `kotlin`):

```
  build: gradle assemble  [builtin]
  lint: gradle detekt  [config]
  tests: gradle test  [builtin]
  coverage: gradle jacocoTestReport  [config]
```

A bare Kotlin `build.gradle(.kts)` lists only `build: gradle assemble` and `tests: gradle test`. Gradle's build
command is `assemble`, not `build`: `gradle build` also runs `test` and `check`, so a failing test or lint would show
as a Build failure and the build gate would hide it. Lint and coverage run only when the build file declares the
plugin id: `io.gitlab.arturbosch.detekt` or `dev.detekt` (`gradle detekt`), `org.jlleitschuh.gradle.ktlint`
(`gradle ktlintCheck`), `jacoco` (`gradle jacocoTestReport`). Text in comments does not count. A lone `detekt.yml`
adds nothing (without the plugin Gradle has no `detekt` task), and Spotless's `ktlint()` step does not add
`ktlintCheck`. A Kotlin project never lists `mvn ...` commands; `--dry-run` shows plain `gradle` (the runner picks
`gradlew` at run time).

---

## go-* (Session 14)

Tiny Go modules, standard library only unless stated. Commands are the Go toolchain's own built-ins:
`go build -o /dev/null ./...`, `go vet ./...`, `go test ./...`, `go test -coverprofile=coverage.out ./...`. The fixtures
are checked by `tests/manual_lang_check.py go`; every fixture is copied to a temp folder and run with `--path <copy>`;
the project is `.`, language `go` (tested since Session 14, so no `[untested]` label). Requires `go` (1.18+) on PATH;
without it every Go run check is shown as `SKIP` (not run: go is not on PATH), and a `SKIP` never counts as passed. The `go-golangci-*` runs also need
`golangci-lint` 2.x on PATH, else they show `SKIP` (not run: golangci-lint is not on PATH). `go-no-tests` needs Go 1.22
or newer: older Go writes an empty profile for a package without tests, and Coverage shows `WARN`. `coverage.out` is
written into the project folder and ignored by each fixture's `.gitignore`.

**Build writes no program file.** With exactly one `package main`, plain `go build ./...` saves the compiled program in
the project folder, and the tool never adds files to user code. `-o /dev/null` builds and writes nothing (also for many
packages). On Windows Go accepts only `NUL` there, so the runner passes `NUL` (and the report shows it); `--dry-run`
shows `/dev/null`.

The Coverage cell is the lowest line percentage from `coverage.out`, a **Go cover profile** (statement coverage; it is
not lcov and has no branch data). A block listed more than once (e.g. with `-coverpkg`) counts once, as `go tool cover`
does.

| Run | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `go-ok` | PASS | PASS | PASS | 100.0% | 0 | |
| `go-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 | syntax error; build gate skips the rest (`build_gate`) |
| `go-test-fail` | PASS | PASS | FAIL | FAIL | 1 | asserts `Add(2, 3) == 6`; the coverage command runs the tests again, so it fails too |
| `go-lint-fail` | PASS | FAIL | PASS | 100.0% | 1 | `go vet` (copylocks) rejects `Show(c Counter)`; `go test` does not run that check, so tests still pass |
| `go-no-tests` | PASS | PASS | SKIP | 0.0% | 0 | no `_test.go`: `? ... [no test files]`, tests `skipped`, reason `no_tests_found` |
| `go-main` | PASS | PASS | PASS | 50.0% | 0 | one `package main`; `main` is not run by the test |
| `go-missing-deps` | WARN | WARN | WARN | WARN | 0 | needs `github.com/google/uuid`; run with `GOPROXY=off`, `GOTOOLCHAIN=local` and an empty `GOMODCACHE` |
| `go-old-toolchain` | WARN | WARN | WARN | WARN | 0 | temp copy of `go-ok` with `go 1.99` in `go.mod`; run with `GOTOOLCHAIN=local` |
| `go-golangci-ok` | PASS | PASS | PASS | 100.0% | 0 | `.golangci.yml` is only `version: "2"` |
| `go-golangci-nofix` | PASS | FAIL | PASS | 100.0% | 1 | badly formatted `calc.go`; the config has `issues: fix: true` |

A module where one package has tests and another has none still shows Tests PASS (the `ok <package>` line counts).

**Report checks:**
- `go-ok`: build `command` is `["go", "build", "-o", "NUL", "./..."]` on Windows, `["go", "build", "-o", "/dev/null",
  "./..."]` elsewhere; coverage has exactly one result with `source_file` `coverage.out`, `format` `gocover`,
  `line_pct` 100.0 (the cover-profile reader, not the percentage in the output); `environment.runners` has a `go` key
  that is not `unknown`.
- `go-build-fail`: build `fail` (never `dependencies_missing`); lint, tests and coverage reason `build_gate`.
- `go-test-fail`: tests `fail`, its output names `want 6`.
- `go-lint-fail`: lint `fail`, its output names `passes lock by value`.
- `go-no-tests`: tests `skipped`, reason `no_tests_found`.
- `go-main`: after the run the copy holds only the fixture's own files plus `coverage.out` and `.pre-llm` (no
  `go-main` / `go-main.exe`).
- `go-missing-deps`, `go-old-toolchain`: build `dependencies_missing`, project warnings include
  `dependencies_missing`, no command is `fail`. Go downloads modules itself; when it cannot (`module lookup disabled by
  GOPROXY=off`, `...@v1.6.0: Get "https://...": ...`, `dial tcp`) or the installed Go is older than `go.mod` needs
  (`go: download go1...`, `go.mod requires go >= ...`), that is a setup problem, not a code failure. `no required module
  provides package` is **not** a dependency phrase: it means `go.mod` lacks a `require` line, a real project error.
- `go-golangci-ok`: lint `command` is `["golangci-lint", "run", "--fix=false"]`, status `pass`.
- `go-golangci-nofix`: lint `fail` (`File is not properly formatted (gofmt)`), and `calc.go` in the copy is byte for
  byte the fixture's `calc.go`: `--fix=false` overrides `issues: fix: true`, so golangci-lint never rewrites code.

**Not applicable for Go:**
- *no-linter*: `go vet` ships with the toolchain, so every Go module has a linter (a `.golangci.yml` replaces it, see
  go-detect).

### go-detect

`go.mod`, `main.go` and a `.golangci.yml` that is only `version: "2"` (golangci-lint 2.x rejects a v1 config with
"unsupported version of the configuration"). Checked with `--dry-run`; nothing is run. Expected lines after the project
line:

```
  build: go build -o /dev/null ./...  [builtin]
  lint: golangci-lint run --fix=false  [config]
  tests: go test ./...  [builtin]
  coverage: go test -coverprofile=coverage.out ./...  [builtin]
```

Without `.golangci.yml` the lint line is `lint: go vet ./...  [builtin]`.
---

## csharp-* (Session 15)

C#/.NET projects (`net8.0`, xunit, `coverlet.collector`). The fixtures are checked by `tests/manual_lang_check.py csharp`;
every run is copied to a temp folder and run with `--path <copy>`; the project is `.`, language `csharp` (tested since
Session 15, so no `[untested]` label). The runs need the **.NET 8 SDK** and internet access to nuget.org the first time
(xunit and coverlet are downloaded once into the NuGet cache; this tool installs nothing). If `dotnet` is not on
PATH, every C# run check is shown as `SKIP` (not run: dotnet is not on PATH); a `SKIP` never counts as passed. Each
fixture's `.gitignore` lists `bin/`, `obj/` and (with a test project) `TestResults/`.

Fixtures:
- `csharp-ok`: `App.sln` lists `Calc/Calc.csproj` (`MathOps.Add`) and `Calc.Tests/Calc.Tests.csproj` (one xunit test,
  `Assert.Equal(5, MathOps.Add(2, 3))`, references `coverlet.collector`).
- `csharp-test-fail`: as `csharp-ok`, the test asserts `Assert.Equal(6, ...)`.
- `csharp-lint-fail`: as `csharp-ok`, `Calc/Calc.cs` has three spaces after `public` on the `Add` line.
- `csharp-build-fail`: only `Calc.csproj` and `Calc.cs` with the `;` missing after `a + b`.
- `csharp-no-tests`: `Calc.sln`, `Calc.csproj` and `Calc.cs` in one folder, no test project.
- `csharp-missing-deps` (no folder): a temp copy of `csharp-ok` run with `NUGET_PACKAGES=<tmp>/nugetpkgs` (an empty
  folder, so packages cached on the PC cannot make it pass) and `RestoreSources=<tmp>/nofeed` (does not exist; MSBuild
  reads environment variables as properties, so restore looks only there and fails with `NU1301`).
- `csharp-old-sdk` (no folder): a temp copy of `csharp-no-tests` with `net8.0` changed to `net99.0` in `Calc.csproj`
  (`NETSDK1045`).

| Run | Build | Lint | Tests | Coverage | Exit |
|---|---|---|---|---|---|
| `csharp-ok` | PASS | PASS | PASS | 100.0% | 0 |
| `csharp-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 |
| `csharp-test-fail` | PASS | PASS | FAIL | FAIL | 1 |
| `csharp-lint-fail` | PASS | FAIL | PASS | 100.0% | 1 |
| `csharp-no-tests` | PASS | PASS | SKIP | SKIP | 0 |
| `csharp-missing-deps` | WARN | WARN | WARN | WARN | 0 |
| `csharp-old-sdk` | WARN | WARN | WARN | SKIP | 0 |

Every run shows exactly one table row. `csharp-test-fail` Coverage is `FAIL` because the coverage command runs the
tests again. `csharp-no-tests` and `csharp-old-sdk` have no coverage command (no `coverlet.collector`, no
`*.runsettings`), so Coverage is `SKIP`.

**Report checks:**
- `csharp-ok`: exactly one project, path `.` (the two `.csproj` are part of the solution); build `command` is
  `["dotnet", "build", "App.sln"]`; coverage has exactly one result with `format` `cobertura`, `line_pct` 100.0 and a
  `source_file` that starts with `Calc.Tests/TestResults/` and ends with `/coverage.cobertura.xml`;
  `environment.runners` has a `dotnet` key that is not `unknown`.
- `csharp-build-fail`: build `fail` (never `dependencies_missing`), its output names `CS1002`; lint, tests and coverage
  reason `build_gate`.
- `csharp-test-fail`: tests `fail`, its output names `Assert.Equal() Failure`.
- `csharp-lint-fail`: lint `fail`, its output names `WHITESPACE`, and `Calc/Calc.cs` in the copy is byte for byte the
  fixture's (`dotnet format --verify-no-changes` changed nothing).
- `csharp-no-tests`: build `command` is `["dotnet", "build", "Calc.sln"]`; lint `pass`; tests `skipped`, reason
  `no_tests_found`.
- `csharp-missing-deps`, `csharp-old-sdk`: build `dependencies_missing`, project warnings include
  `dependencies_missing`, no command is `fail`.

Rules shown:
- **`{build_file}`.** Every command names the primary build file (the `.sln` / `.slnx`, else the `.csproj`):
  `dotnet build {build_file}`, `dotnet format {build_file} --verify-no-changes`, `dotnet test {build_file}`. In a folder
  with both a `.sln` and a `.csproj`, plain `dotnet format` crashes ("Both a MSBuild project file and solution file
  found") and plain `dotnet test` runs no test and exits 0. `csharp-no-tests` proves the fix (Lint `PASS`).
- **Solutions.** A `.csproj` that a `.sln` / `.slnx` in an ancestor folder lists is built by that solution, so it is
  part of the solution's project (like Maven modules and Gradle subprojects; languages.toml `subproject_rules`
  `"*.sln"` / `"*.slnx"` = `dotnet_solution`). A `.csproj` the solution does not list stays its own project.
  `.sln` wins over `.csproj` in one folder (both stay in `build_files`).
- **`.slnx`.** The .NET 10 SDK writes `.slnx` (XML) by default; it is a build file like `.sln`, and every `Project`
  element's `Path` (also inside `Folder`) counts as listed.
- **No tests.** `dotnet test` prints one `Passed!  - Failed: 0, Passed: N, ...` line per test project that ran. A test
  project with no tests prints `No test is available in ...`; a solution or project with no test project prints no
  `Passed!` line. Either way Tests is `SKIP` (`no_tests_found`), never a vacuous `PASS`.
- **Dependencies.** `dotnet` downloads NuGet packages itself. When it cannot (`error NU1100`-`NU1103`: package not
  found / no matching version; `error NU1301`-`NU1302`: feed unreachable; `error NETSDK1004`: packages never restored;
  `dotnet format`: `Restore operation failed.`) or the installed SDK is older than the target framework
  (`error NETSDK1045`), that is a setup problem: `dependencies_missing` (WARN), not a failure. Other `NU` errors, such
  as `NU1605` (package downgrade), are real project errors and stay `FAIL`.
- **Coverage** is not built-in. It runs (`dotnet test {build_file} --collect:"XPlat Code Coverage"`) only when the
  project file, or for a solution any `.csproj` it lists, references `coverlet.collector` (XML comments ignored), or a
  `*.runsettings` file sits next to the build file. It is read from `**/TestResults/*/coverage.cobertura.xml` (where
  `dotnet test` writes it, inside the test project folder, in a fresh GUID folder per run); files from earlier runs are
  stale by mtime and ignored.
- **Lint.** `dotnet format --verify-no-changes` ships with the SDK and never writes files, so every .NET project has a
  linter (*no-linter* is not applicable).

### csharp-detect

`App.Tests.csproj` references `coverlet.collector`. Checked with `--dry-run`; nothing is run. Expected lines after the
project line (language `csharp`):

```
  build: dotnet build App.Tests.csproj  [builtin]
  lint: dotnet format App.Tests.csproj --verify-no-changes  [builtin]
  tests: dotnet test App.Tests.csproj  [builtin]
  coverage: dotnet test App.Tests.csproj --collect:XPlat Code Coverage  [config]
```

(the last argument is a single argument, `--collect:XPlat Code Coverage`; `--dry-run` joins arguments with spaces.)

## rust-* (Session 16)

Tiny crates (edition 2021). The fixtures are checked by `tests/manual_lang_check.py rust`; every run is copied to a temp
folder and run with `--path <copy>`; the project is `.`, language `rust [untested]`. The runs need `cargo` with the
`clippy` component on PATH (`cargo clippy` ships with rustup's default profile). If `cargo` is not on PATH, every Rust
run check is shown as `SKIP` (not run: cargo is not on PATH); a `SKIP` never counts as passed. Only
`rust-missing-deps` has a dependency, and it runs offline, so no run needs internet. Each fixture's `.gitignore` lists
`target/`, `Cargo.lock` and `cobertura.xml`: cargo writes `Cargo.lock` and `target/` in the project folder (standard
cargo behaviour; this tool writes nothing there except `.pre-llm/`).

Fixtures:
- `rust-ok`: `add(a, b)` and one test, `assert_eq!(add(2, 3), 5)`.
- `rust-build-fail`: as `rust-ok`, the body is `a + ;` (syntax error).
- `rust-test-fail`: as `rust-ok`, the test asserts `add(2, 3) == 6`.
- `rust-lint-fail`: `#![deny(clippy::needless_return)]` plus `return a + b;`: clippy errors; rustc and `cargo test` do
  not run clippy lints.
- `rust-no-tests`: `rust-ok` without the `#[cfg(test)]` module.
- `rust-workspace`: the root `Cargo.toml` has only `[workspace]` (`members = ["crates/*"]`, `resolver = "2"`);
  `crates/calc-a` and `crates/calc-b` each have `add` and one test (`member_a_adds` / `member_b_adds`).
- `rust-missing-deps`: depends on `itoa = "1"`, no `Cargo.lock`. Run with `CARGO_NET_OFFLINE=true` and
  `CARGO_HOME=<tmp>/cargohome` (an empty folder, so a copy of `itoa` cached on the PC cannot make it pass; no internet
  needed).
- `rust-old-toolchain` (no folder): a temp copy of `rust-ok` with `rust-version = "1.999"` added after
  `edition = "2021"`.
- `rust-no-linker` (no folder): a temp copy of `rust-ok` run with `RUSTFLAGS=-C linker=pre-llm-no-such-linker` (a
  linker that does not exist). `cargo build` and `cargo clippy` of a library do not link, so they pass; `cargo test`
  must link the test binary and fails with ``error: linker `pre-llm-no-such-linker` not found``. Needs no real
  linker, so it works on any PC with cargo.
- `rust-tarpaulin`: `rust-ok` plus a `tarpaulin.toml` that holds only a comment. With `cargo-tarpaulin` on PATH the
  Coverage cell must be a percentage; without it, the Coverage cell must be `WARN` (cargo says
  ``no such command: `tarpaulin` ``). It is never `SKIP` when `cargo` is present; the check prints which branch ran.

| Run | Build | Lint | Tests | Coverage | Exit |
|---|---|---|---|---|---|
| `rust-ok` | PASS | PASS | PASS | SKIP | 0 |
| `rust-build-fail` | FAIL | SKIP | SKIP | SKIP | 1 |
| `rust-test-fail` | PASS | PASS | FAIL | SKIP | 1 |
| `rust-lint-fail` | PASS | FAIL | PASS | SKIP | 1 |
| `rust-no-tests` | PASS | PASS | SKIP | SKIP | 0 |
| `rust-workspace` | PASS | PASS | PASS | SKIP | 0 |
| `rust-missing-deps` | WARN | WARN | WARN | SKIP | 0 |
| `rust-old-toolchain` | WARN | WARN | WARN | SKIP | 0 |
| `rust-no-linker` | PASS | PASS | WARN | SKIP | 0 |
| `rust-tarpaulin`, `cargo-tarpaulin` on PATH | PASS | PASS | PASS | *percentage* | 0 |
| `rust-tarpaulin`, `cargo-tarpaulin` not on PATH | PASS | PASS | PASS | WARN | 0 |

Every run shows exactly one table row. Only `rust-tarpaulin` has a coverage command, so Coverage is `SKIP` elsewhere.

**Report checks:**
- `rust-ok`: build `command` is `["cargo", "build", "--workspace"]`, status `pass`; `environment.runners` has a `cargo`
  key that is not `unknown`; after the run the copy holds only the fixture's own files plus `Cargo.lock`, `target` and
  `.pre-llm`.
- `rust-build-fail`: build `fail` (never `dependencies_missing`); lint, tests and coverage reason `build_gate`.
- `rust-test-fail`: tests `fail`, its output names `right: 6`.
- `rust-lint-fail`: lint `fail`, its output names `needless_return`.
- `rust-no-tests`: tests `skipped`, reason `no_tests_found`.
- `rust-workspace`: exactly one project, path `.`; its tests output names both `member_a_adds` and `member_b_adds`.
- `rust-missing-deps`, `rust-old-toolchain`: build `dependencies_missing`, project warnings include
  `dependencies_missing`, no command is `fail`; `rust-old-toolchain`'s build output names `requires rustc 1.999`.
- `rust-no-linker`: tests `dependencies_missing`, its output names ``linker `pre-llm-no-such-linker` not found``;
  project warnings include `dependencies_missing`; no command is `fail`.
- `rust-tarpaulin` with `cargo-tarpaulin`: coverage `command` is
  `["cargo", "tarpaulin", "--workspace", "--out", "Xml", "--output-dir", "."]`, status `pass`; coverage has exactly
  one result with `source_file` `cobertura.xml`, `format` `cobertura`, `line_pct` above 0 and `branch_pct` null
  (proves the file was read, not a percentage from the output).
- `rust-tarpaulin` without `cargo-tarpaulin`: coverage `dependencies_missing`, its output names
  ``no such command: `tarpaulin` ``.

Rules shown:
- **`--workspace`.** Every command is `cargo build --workspace`, `cargo clippy --workspace`, `cargo test --workspace`.
  In a workspace whose root is also a package, plain `cargo build` builds only the root package; on a single crate
  `--workspace` changes nothing.
- **Workspaces.** A crate listed in a parent `Cargo.toml`'s `[workspace] members` (globs expanded, minus `exclude`)
  is built by the workspace root, so it is part of the root project (languages.toml `subproject_rules`
  `"Cargo.toml"` = `cargo_workspace`). Before, `rust-workspace` showed 3 projects and built and tested each member
  twice. A crate under a `Cargo.toml` without a `[workspace]` table, or one the workspace excludes, stays its own
  project; an unparsable root `Cargo.toml` claims nothing.
- **No tests.** `cargo test` prints `running N tests` once per test target (unit, integration, doc). When every one is
  `running 0 tests`, nothing ran: Tests is `SKIP` (`no_tests_found`), never a vacuous `PASS`.
- **Coverage** is not built-in: `cargo tarpaulin` is a separate install. It runs
  (`cargo tarpaulin --workspace --out Xml --output-dir .`) only when the crate has a `tarpaulin.toml` or
  `.tarpaulin.toml`, the only places tarpaulin reads config from. A `[package.metadata.tarpaulin]` table does not count
  (tarpaulin never reads it). `--output-dir .` keeps `cobertura.xml` where the reader looks even if the config sets
  `output-dir`. When tarpaulin finds no coverable lines it writes `line-rate="NaN"` with `lines-valid="0"`: that is
  no coverage data (not `nan%`). It measures no branches (`branches-valid="0"`), so `branch_pct` is null, not 0.
- **Dependencies.** Setup problems only are `dependencies_missing` (WARN): `failed to download from `` ` ``,
  `offline mode (`, `requires rustc ` (a `rust-version` newer than the installed rustc), ``no such command: ` ``
  (a cargo subcommand such as `tarpaulin` not installed), `is not installed for the toolchain` (the clippy component
  missing), the pattern ``unable to update (registry `|https?://|ssh://|git@)`` (fetching the registry or a git
  dependency failed), and the pattern ``^error: linker `[^`]+` not found`` (no linker installed: on Windows the
  Visual Studio C++ Build Tools are missing (`link.exe`), on macOS/Linux `cc`; before, this showed Tests `FAIL` and
  exit 1 on fine code). ``error: linking with `cc` failed`` is not matched: that is a real link error in the
  project's code. The earlier phrases were wrong: `no matching package` (a misspelt crate name),
  `failed to select a version` (a version that does not exist) and ``failed to get ` `` (a missing path dependency)
  are real project errors, and they showed `WARN` with exit 0. `could not compile` and `error[E` appear for every
  rustc error and were never phrases. A too-new `rust-version` showed Build `FAIL`, a missing `cargo-tarpaulin`
  Coverage `FAIL`.
- **Windows linker.** The default Rust toolchain on Windows (`x86_64-pc-windows-msvc`) needs the Visual Studio C++
  Build Tools to link tests. Without them every Rust run except `rust-build-fail`, `rust-missing-deps`,
  `rust-old-toolchain` and `rust-no-linker` shows Tests `WARN` instead of its expected cells. To run them all, use the
  GNU toolchain (`rustup default stable-x86_64-pc-windows-gnu`, which has its own linker) or install the Build Tools.
- **Lint.** `cargo clippy` ships with rustup's default profile and never changes code, so every crate has a linter
  (*no-linter* is not applicable). `cargo fmt` is not run (without `--check` it rewrites code).

### rust-detect

`Cargo.toml` (no `[package.metadata.tarpaulin]`) and a `.tarpaulin.toml` that holds only a comment. Checked with
`--dry-run`; nothing is run. Expected lines after the project line:

```
  build: cargo build --workspace  [builtin]
  lint: cargo clippy --workspace  [builtin]
  tests: cargo test --workspace  [builtin]
  coverage: cargo tarpaulin --workspace --out Xml --output-dir .  [config]
```

## php-* (Session 17)

PHP has **no build stage**: the Build cell is always `SKIP`. The fixtures are checked by
`tests/manual_lang_check.py php`; every run is copied to a temp folder and run with `--path <copy>`; the project is
`.`, language `php [untested]`. A check whose tool is not on PATH is shown as `SKIP` (not run: php is not on PATH /
composer is not on PATH / composer install failed: ...); a `SKIP` never counts as passed.

The php-unit runs need PHP 8.2+ and Composer on PATH, and internet the first time: PHPUnit and PHP_CodeSniffer are
downloaded **once** into a temp folder (`composer install` in a copy of `php-unit-ok`) **by the check itself, never by
the tool**, and that `vendor/` is copied into each php-unit run (Composer's autoloader uses relative paths). Without a
coverage driver (PCOV, or Xdebug in coverage mode) Coverage is `WARN` (`dependencies_missing`); with one it is a
percentage read from `clover.xml`. The check prints which case it found. Each new fixture's `.gitignore` lists
`vendor/`, `composer.lock`, `clover.xml`, `.phpunit.cache/`, `.phpunit.result.cache`.

Fixtures:
- `php-unit-ok`: `composer.json` (`require-dev` phpunit/phpunit ^11.5 and squizlabs/php_codesniffer ^3.13, PSR-4
  autoload `App\` → `src/`), `phpunit.xml` (bootstrap `vendor/autoload.php`, suite `tests`, source `src`),
  `phpcs.xml` (PSR12 on `src`), `src/Calc.php` (`Calc::add`), `tests/CalcTest.php` (`assertSame(5, Calc::add(2, 3))`).
- `php-unit-test-fail`: as `php-unit-ok`, the test says `assertSame(6, Calc::add(2, 3))`.
- `php-unit-lint-fail`: as `php-unit-ok`, `src/Calc.php` has three spaces after `public`.
- `php-unit-no-tests`: as `php-unit-ok`, `tests/` holds only an empty `.gitkeep`.
- `php-unit-missing-deps` (no folder): a copy of `php-unit-ok` without `vendor/`.
- `php-scripts`: `calc.php` and `run_tests.php` from `php-ok`; `composer.json` declares no packages, only the scripts
  `lint` = `php -l calc.php`, `test` = `php run_tests.php`.
- `php-fixer-script`: as `php-scripts`, but `lint` = `["php -l calc.php", "@cs"]` and `cs` =
  `phpcbf --standard=PSR12 calc.php`.

| Run | Made from | Needs | Build | Lint | Tests | Coverage (driver) | Coverage (no driver) | Exit |
|---|---|---|---|---|---|---|---|---|
| `php-unit-ok` | `php-unit-ok` | php, composer | SKIP | PASS | PASS | 100.0% | WARN | 0 |
| `php-unit-test-fail` | `php-unit-test-fail` | php, composer | SKIP | PASS | FAIL | FAIL | WARN | 1 |
| `php-unit-lint-fail` | `php-unit-lint-fail` | php, composer | SKIP | FAIL | PASS | 100.0% | WARN | 1 |
| `php-unit-no-tests` | `php-unit-no-tests` | php, composer | SKIP | PASS | SKIP | *percentage* or WARN | WARN | 0 |
| `php-unit-missing-deps` | copy of `php-unit-ok`, no `vendor/` | nothing | SKIP | SKIP | SKIP | SKIP | SKIP | 0 |
| `php-scripts` | `php-scripts` | php, composer | SKIP | PASS | PASS | SKIP | SKIP | 0 |
| `php-fixer-script` | `php-fixer-script` | php, composer | SKIP | WARN | PASS | SKIP | SKIP | 0 |

Every run shows exactly one table row.

**Report checks:**
- `php-unit-ok`: tests `command` is `["vendor/bin/phpunit", "--no-coverage", "--do-not-cache-result"]`, status `pass`;
  lint `command` is `["vendor/bin/phpcs"]`, status `pass`; after the run the copy has no `.phpunit.result.cache`.
  No driver: coverage status `dependencies_missing`, its output names `No code coverage driver`. Driver: coverage has
  exactly one result with `source_file` `clover.xml`, `format` `clover`, `line_pct` 100.0 (proves the Clover reader
  read the file, not a percentage from the output).
- `php-unit-test-fail`: tests `fail`, its output names `Failed asserting that 5 is identical to 6`.
- `php-unit-lint-fail`: lint `fail`, its output names `must be followed by a single space`; `src/Calc.php` in the copy
  is byte-for-byte the fixture's after the run (phpcs fixed nothing).
- `php-unit-no-tests`: tests `skipped`, reason `no_tests_found`.
- `php-unit-missing-deps`: every stage entry is `skipped` with a reason starting `dependencies_missing`; project
  warnings include `dependencies_missing`.
- `php-scripts`: lint `command` `["composer", "lint"]` and tests `command` `["composer", "test"]`, both `pass`; project
  warnings do not include `dependencies_missing`.
- `php-fixer-script`: lint status `no_linter_configured`; tests `["composer", "test"]`, status `pass`; `calc.php` in
  the copy is byte-for-byte the fixture's after the run; `--dry-run` of the fixture prints the lines
  `skipped: lint  (command runs a fixer)` and `skipped: cs  (command runs a fixer)`.

### Override fixtures (php-ok, php-test-fail, php-lint-fail, php-no-tests, php-no-linter)

These replace the tools with the PHP interpreter through `pre-llm.toml`: `lint` = `php -l <file>` (syntax check),
`tests` = `php run_tests.php` (plain assertions, exit 1 on failure). They need only `php` on PATH. Commands that come
only from `pre-llm.toml` skip the `vendor` folder check. **They prove only that `pre-llm.toml` overrides work, not PHP
detection**; the php-unit runs above prove detection.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `php-ok` | SKIP | PASS | PASS | SKIP | 0 | |
| `php-test-fail` | SKIP | PASS | FAIL | SKIP | 1 | asserts `add(2, 3) === 6` |
| `php-lint-fail` | SKIP | FAIL | PASS | SKIP | 1 | `php -l bad.php` reports a parse error; `bad.php` is not loaded by the tests |
| `php-no-tests` | SKIP | PASS | SKIP | SKIP | 0 | no tests command, no `phpunit.xml`, no composer script: tests stage skipped (`nothing_to_run`) |
| `php-no-linter` | SKIP | WARN | PASS | SKIP | 0 | no lint command, no phpcs/phpstan/psalm config: `no_linter_configured` |

### php-detect

`composer.json` (no scripts) plus `phpunit.xml`, `phpcs.xml`, `phpstan.neon`. Checked with `--dry-run`. Expected lines
after the project line (no `build:` line; two lint commands, in rule order):

```
  lint: vendor/bin/phpcs  [config]
  lint: vendor/bin/phpstan analyse  [config]
  tests: vendor/bin/phpunit --no-coverage --do-not-cache-result  [config]
  coverage: vendor/bin/phpunit --do-not-cache-result --coverage-clover clover.xml  [config]
```

Rules shown:
- **No build stage, nothing built-in.** A tool runs only when the project declares it: a `composer.json` script or a
  config file next to `composer.json`. `require-dev` entries alone detect nothing.
- **Config files.** `phpunit.xml`, `phpunit.xml.dist`, `phpunit.dist.xml` → tests and coverage (PHPUnit); `phpcs.xml`,
  `phpcs.xml.dist`, `.phpcs.xml`, `.phpcs.xml.dist` → `vendor/bin/phpcs`; `phpstan.neon`, `phpstan.neon.dist`,
  `phpstan.dist.neon` → `vendor/bin/phpstan analyse`; `psalm.xml`, `psalm.xml.dist` → `vendor/bin/psalm`;
  `.php-cs-fixer.php`, `.php-cs-fixer.dist.php` → `vendor/bin/php-cs-fixer fix --dry-run --diff --using-cache=no`.
  New this session: `phpunit.dist.xml` (PHPUnit 10+), `.phpcs.xml.dist`, `phpstan.dist.neon`. The unused
  `[language.php.config_files]` table is gone (the `config_commands` rules do the work, as for Go and Rust).
- **Composer scripts win** for their stage and are run as `composer <script>`.
- **Fixer scripts are skipped** (golden rule: never run fixers), reason `command runs a fixer`: `phpcbf`,
  `php-cs-fixer fix` without `--dry-run`, `pint` without `--test`, `rector` without `--dry-run`, `psalter`,
  `psalm --alter`. These rewrite code with no `--fix`/`--write` flag. Every command a script runs is checked: every
  item of a list script, and every `@other-script` it references, recursively (`@php`, `@composer`, `@putenv` are
  Composer built-ins, not references; a reference cycle stops). Before, `"lint": "phpcbf"` reformatted the user's file,
  and only the first list item was looked at.
- **vendor/** is expected only when `composer.json` declares `require`, `require-dev`, `autoload` or `autoload-dev`.
  A `composer.json` with only scripts (`php-scripts`) needs no `composer install`; before, every stage showed `SKIP`
  with `dependencies_missing`.
- **Project-relative tools** such as `vendor/bin/phpunit` are resolved against the project folder. On Windows the
  `.bat` Composer writes next to it is used (then `.cmd`, `.exe`); the extensionless file is a PHP proxy script Windows
  cannot launch, so it is never used there.
- **`--no-coverage --do-not-cache-result`** on the tests command: the tests stage never writes coverage reports set in
  `phpunit.xml`, and PHPUnit writes no `.phpunit.result.cache` into the project (it did on every run). The coverage
  command also has `--do-not-cache-result`. `--using-cache=no` stops php-cs-fixer writing `.php-cs-fixer.cache`.
- **Coverage** is read from `clover.xml` by the Clover reader: the project totals (`<project><metrics>`),
  `coveredstatements / statements`; branch coverage only when `conditionals` > 0 (PHPUnit always writes 0, so
  `branch_pct` is null). Before, `clover.xml` was read as Cobertura and was always `coverage_unreadable`.
- **No tests.** PHPUnit prints `No tests executed!` and exits 0 when there is nothing to run: Tests is `SKIP`
  (`no_tests_found`), never a vacuous `PASS`. A run that executed tests prints `OK (N tests, ...` or `Tests: N, ...`.
- **Dependencies.** `dependencies_missing` (WARN) is recognised by `vendor/autoload.php` (`composer install` never ran),
  `No code coverage driver available` / `No code coverage driver is available` and
  `xdebug.mode=coverage (PHP configuration setting) has to be set` (no coverage driver: PHPUnit 11 exits 1 with that
  warning, which used to show Coverage `FAIL` and exit 1 on fine code; it is not `coverage_missing`, as this file used
  to say). `Your requirements could not be resolved` and `Composer could not find` were dropped: only
  `composer install`/`update` print them, and the tool never runs those. `No such file or directory` stays out: PHP
  prints it for any failed include in the project's own code.

---

## ruby-* (Session 18)

Ruby has **no build stage**: the Build cell is always `SKIP`. Checked by `python tests/manual_lang_check.py ruby`.

### Override fixtures (need only `ruby`)

These use the Ruby interpreter and the minitest that ships with it, through `pre-llm.toml`: `lint` = `ruby -c <file>`
(syntax check), `tests` = `ruby test_calc.rb`. Run with `--path <copy>`; the project is `.`, language
`ruby` (tested since Session 18, so no `[untested]` label). They prove only that `pre-llm.toml` overrides work with
a Ruby project, **not** Ruby detection.

| Fixture | Build | Lint | Tests | Coverage | Exit | Notes |
|---|---|---|---|---|---|---|
| `ruby-ok` | SKIP | PASS | PASS | SKIP | 0 | |
| `ruby-test-fail` | SKIP | PASS | FAIL | SKIP | 1 | asserts `add(2, 3) == 6` |
| `ruby-lint-fail` | SKIP | FAIL | PASS | SKIP | 1 | `ruby -c bad.rb` reports a syntax error; `bad.rb` is not loaded by the tests |
| `ruby-no-tests` | SKIP | PASS | SKIP | SKIP | 0 | no tests command, no `.rspec`: tests stage skipped (`nothing_to_run`) |
| `ruby-no-linter` | SKIP | WARN | PASS | SKIP | 0 | no lint command, no `.rubocop.yml` / `.standard.yml`: `no_linter_configured` |

### Real Bundler runs

Each run is made in a temp copy (the repo is never written). The rspec runs need `bundle` and the gems `rspec`,
`rubocop` and `simplecov` (and `standard` for ruby-standard) **already installed by the user**: neither the tool nor
the check ever installs gems, and they work offline. Without them those runs show `SKIP` (never counted as passed).
The missing-gem runs set `GEM_HOME` and `GEM_PATH` to an empty folder: Bundler and RubyGems are default gems and still
load, every other gem (minitest, rspec, ...) is hidden.

| Run | Made from | Needs | Build | Lint | Tests | Coverage | Exit |
|---|---|---|---|---|---|---|---|
| `ruby-rspec-ok` | `ruby-rspec-ok` | ruby, bundle, gems | SKIP | PASS | PASS | 80.0% | 0 |
| `ruby-rspec-test-fail` | copy of `ruby-rspec-ok`, `spec/calc_spec.rb`: `eq(5)` → `eq(6)` | ruby, bundle, gems | SKIP | PASS | FAIL | FAIL | 1 |
| `ruby-rspec-lint-fail` | copy of `ruby-rspec-ok`, `lib/calc.rb`: `unused = 1` added before `first + second` | ruby, bundle, gems | SKIP | FAIL | PASS | a percentage | 1 |
| `ruby-rspec-no-specs` | copy of `ruby-rspec-ok` without `spec/calc_spec.rb` | ruby, bundle, gems | SKIP | PASS | SKIP | SKIP | 0 |
| `ruby-rspec-missing-gems` | copy of `ruby-rspec-ok`, empty gems folder | ruby, bundle | SKIP | WARN | WARN | WARN | 0 |
| `ruby-standard` | `ruby-standard` | ruby, bundle, gem standard | SKIP | FAIL | SKIP | SKIP | 1 |
| `ruby-require-typo` | copy of `ruby-ok`, `test_calc.rb`: `require_relative "calc"` → `"calcc"` | ruby | SKIP | PASS | FAIL | SKIP | 1 |
| `ruby-missing-minitest` | copy of `ruby-ok`, empty gems folder | ruby | SKIP | PASS | WARN | SKIP | 0 |

Report checks:
- **ruby-rspec-ok**: lint command `["bundle", "exec", "rubocop"]`, tests and coverage `["bundle", "exec", "rspec"]`,
  all `pass`. Coverage has exactly one result: `source_file` `coverage/.last_run.json`, `format` `simplecov`,
  `line_pct` 80.0, `branch_pct` 0.0 (SimpleCov's own totals were read, not the output). `environment.runners` has a
  `bundle` version (not `unknown`). Afterwards the copy holds only the fixture's files plus `Gemfile.lock`,
  `coverage/` and `.pre-llm/`.
- **ruby-rspec-test-fail**: tests `fail` (not `dependencies_missing`), output names `expected: 6`.
- **ruby-rspec-lint-fail**: lint `fail`, output names `Lint/UselessAssignment`, and `lib/calc.rb` is byte-for-byte the
  edited file (RuboCop changed nothing).
- **ruby-rspec-no-specs**: tests and coverage both `skipped`, reason `no_tests_found`; no coverage results.
- **ruby-rspec-missing-gems**: lint, tests and coverage `dependencies_missing`; project warning `dependencies_missing`;
  no command `fail`.
- **ruby-standard**: lint command `["bundle", "exec", "standardrb", "--no-fix"]`, status `fail`, output names
  `Style/RedundantReturn`, and `calc.rb` is byte-for-byte the fixture's (the `.standard.yml` says `fix: true`).
- **ruby-require-typo**: tests `fail` (not `dependencies_missing`), output names `cannot load such file`.
- **ruby-missing-minitest**: tests `dependencies_missing`, output names `minitest/autorun`.

### ruby-detect, ruby-minitest-detect (`--dry-run` only)

`ruby-detect`: `Gemfile` (lists rspec, rubocop and simplecov), `.rspec`, `.rubocop.yml`. Expected lines after the
project line (no `build:` line):

```
  lint: bundle exec rubocop  [config]
  tests: bundle exec rspec  [config]
  coverage: bundle exec rspec  [config]
```

`ruby-minitest-detect`: `Gemfile` (minitest, rubocop, simplecov), `.simplecov`, `.rubocop.yml`, no `.rspec`. Expected:

```
  lint: bundle exec rubocop  [config]
```

No tests line (minitest has no config file to detect) and no coverage line: coverage needs `.rspec`.

### Rules

- **No build stage, nothing built-in.** A tool runs through `bundle exec` only when the project declares it with a
  config file next to the `Gemfile`: `.rspec` → tests `bundle exec rspec`; `.rubocop.yml` / `.rubocop.yaml` →
  `bundle exec rubocop`; `.standard.yml` → `bundle exec standardrb --no-fix`. A Gemfile that merely lists a gem detects
  nothing. The dead `stage_names` and `config_files` tables are gone (as for Go, Rust and PHP).
- **`--no-fix`.** A `.standard.yml` with `fix: true` makes plain `standardrb` rewrite the user's files and report
  PASS; with `--no-fix` the file stays unchanged and Lint is FAIL.
- **Coverage** = the specs run again under SimpleCov. The rule needs `.rspec` (`requires_files`: every listed file must
  be next to the build file) **and** SimpleCov declared: a `.simplecov` file or `"simplecov"` / `'simplecov'` (with
  quotes, so `simplecov-lcov` alone does not count) in the Gemfile. Before, a minitest project with `simplecov` in its
  Gemfile got `bundle exec rspec`, which fails (`rspec-core is not currently included in the bundle`): Coverage FAIL,
  exit 1, on fine code.
- **Coverage is read from `coverage/.last_run.json`**, SimpleCov's own totals (`{"result": {"line": 80.0, "branch":
  0.0}}`; older SimpleCov: `covered_percent`), the numbers it prints. `.resultset.json` is no longer read: it is raw
  data before `# :nocov:` and other exclusions (it gave 71.43% where SimpleCov said 80.00%). SimpleCov writes
  `.last_run.json` only after a passing run; otherwise the printed `Line coverage: 4 / 5 (80.00%)` (SimpleCov 1.x) or
  `Line Coverage: 91.2%` (0.22) number is used.
- **No tests.** RSpec `0 examples, 0 failures` and minitest `0 runs, 0 assertions` exit 0: Tests is `SKIP`
  (`no_tests_found`), never a vacuous PASS. A run with tests prints `N example(s), ...` / `N run(s), ...`.
  `coverage_needs_tests = true` gives the coverage stage the same check (SimpleCov says 100% when no test ran), and no
  coverage is read then.
- **Dependencies.** `dependencies_missing` (WARN) is recognised by `Could not find gem '`, `Bundler::GemNotFound`,
  `Gem::MissingSpecError`, ``Run `bundle install` to install missing gems`` and
  ``Install missing gem executables with `bundle install` `` (Bundler 4 prints the last one for
  `bundler: command not found: rspec`; before, Lint, Tests and Coverage were FAIL), and the pattern
  `cannot load such file -- ` followed by a library name, not a path. The old phrase `cannot load such file` also
  matched `require_relative` of a misspelt file (`cannot load such file -- /full/path/calcc`), a real code error, and
  turned that Tests FAIL into WARN with exit 0. A misspelt gem name in the Gemfile gives the same message as a missing
  gem; offline the two cannot be told apart. `vendor/bundle` is not required (most projects use system or user gems).
- **Files written into the project.** `bundle exec` writes `Gemfile.lock` and SimpleCov writes `coverage/` into the
  project folder (standard Bundler and SimpleCov behaviour); the fixtures' `.gitignore` lists them.

## swift-* (Session 19)

Swift **Package Manager only**. Checked by `python tests/manual_lang_check.py swift`. Each run is made in a temp copy
(the repo is never written) and run with `--path <copy>`; the project is `.`, language `swift [untested]`. `.build/` is
ignored by each fixture's `.gitignore`.

The runs need `swift` with XCTest on PATH: full Xcode on Mac (the Command Line Tools alone have no XCTest; Xcode 16 or
newer for `swift format`), the Swift toolchain on Windows and Linux. The SwiftLint and SwiftFormat runs need
`swiftlint` and `swiftformat` on PATH, and the swift-format runs need `swift format`; without them those runs show
`SKIP` (never counted as passed). No fixture has dependencies that download, and swift-missing-deps needs no internet.

On macOS the Swift runs need **full Xcode**: the Command Line Tools have no XCTest (`swift test` prints
`error: XCTest not available`), and SwiftLint needs Xcode's SourceKit (without it SwiftLint crashes with
`Loading sourcekitdInProc ... failed`). Without Xcode the tool shows WARN (`dependencies_missing`) for Tests, Coverage
and SwiftLint, and the manual check shows every Swift run as SKIP (not run: XCTest not available: install full Xcode and
run `sudo xcode-select -s /Applications/Xcode.app`); swift-detect still runs. On Windows, Swift needs Visual Studio's
C++ tools and the Windows SDK; without them every build fails with `could not build C module 'SwiftShims'`, the tool
shows WARN (`dependencies_missing`), and the manual check shows the Swift runs as SKIP.

### Rules

- **Swift Package Manager only.** The build file is `Package.swift`; build, tests and coverage are the SwiftPM
  built-ins `swift build`, `swift test` and `swift test --enable-code-coverage`. An Xcode project (`*.xcodeproj`) is a
  folder, not a file, and needs `xcodebuild` plus a scheme, which cannot be guessed: Xcode projects are not supported
  (a folder with only `App.xcodeproj` and `.swift` files is not a Swift project).
- **Lint only from config files.** Lint is not built in. It runs only when the project has the tool's config file:
  - SwiftLint, `.swiftlint.yml` → `swiftlint lint --quiet`. SwiftLint reads only `.swiftlint.yml` on its own; with
    only `.swiftlint.yaml` it would lint with its default rules, not the project's, so that name is not detected.
  - SwiftFormat (nicklockwood), `.swiftformat` → `swiftformat --lint .`. SwiftFormat rewrites files by default; only
    its read-only `--lint` form is ever run. `swiftformat.yml` is not a SwiftFormat file name.
  - swift-format (Apple, ships with Swift 6 / Xcode 16), `.swift-format` → `swift format lint --strict --recursive .`.
    Without `--strict` every finding is a warning and it exits 0, so Lint would always pass.
- **Coverage** is `swift test --enable-code-coverage` (the tests run again). SwiftPM writes an llvm-cov JSON export to
  `.build/<platform>/debug/codecov/<package>.json`, read by the `llvmcov` reader. Only the package's own sources count:
  not `Tests/` (the test targets), not `.build/` (SwiftPM's generated test runner), not files outside the package. The
  export's own totals mix those in (23.38% instead of 33.33% for a package where `Calc.swift` had 3 of 9 lines
  covered), so they are not used. Swift writes no branch data: `branch_pct` is null.
- **No tests.** A package with no test target: `swift test` prints `error: no tests found` and exits 1 → Tests `SKIP`
  (`no_tests_found`), not FAIL. A test target with no tests: XCTest prints `Executed 0 tests` and swift-testing
  `Test run with 0 tests`, exit 0 → Tests `SKIP` (`no_tests_found`), not a vacuous PASS. Coverage is the tests run
  again, so it is `SKIP` (`no_tests_found`) too, with no `coverage_missing` warning.
- **Dependency phrases** (`fail` → `dependencies_missing`, a warning): `error: Failed to clone repository ` and
  `Couldn't fetch updates from remote repositories` (SwiftPM could not download a package: offline or blocked),
  `is using Swift tools version ... but the installed version is ...` (`Package.swift` needs a newer Swift),
  `no such module 'XCTest'` / `no such module 'Testing'` (a toolchain without the test frameworks), and
  `unknown or missing subcommand 'swift-format'` (a Swift without `swift format`). **Not** `no such module` alone: a
  misspelt import (`import Foundaton`) prints it too, and that is a real code error (Build FAIL).
- `.build/` is written into the project by SwiftPM (like Rust's `target/`) and holds the dependency checkouts, each
  with its own `Package.swift`: discovery skips it. SwiftLint has no option to exclude `.build/` by itself, so a project
  whose `.swiftlint.yml` does not exclude it also gets its downloaded packages linted.

### Override fixtures

`swift-ok`, `swift-build-fail`, `swift-test-fail`, `swift-lint-fail` use a `pre-llm.toml` lint override that uses the
compiler's parser, `swiftc -parse <file>`; `swift-no-linter` has none. They prove only that `pre-llm.toml` lint
overrides and the SwiftPM built-ins work, **not** Swift lint detection (that is the swift-swiftlint, swift-swiftformat
and swift-swift-format runs). They are the first five rows of the table below.

(The test function is called `sum`, not `add`: `XCTestCase` already has an `add` method, and `add(2, 3)` inside a
test class fails to compile.)

### Real Swift runs

| Run | Made from | Extra tool | Build | Lint | Tests | Coverage | Exit |
|---|---|---|---|---|---|---|---|
| `swift-ok` | `swift-ok` | | PASS | PASS | PASS | 100.0% | 0 |
| `swift-build-fail` | `swift-build-fail` | | FAIL | SKIP | SKIP | SKIP | 1 |
| `swift-test-fail` | `swift-test-fail` | | PASS | PASS | FAIL | FAIL | 1 |
| `swift-lint-fail` | `swift-lint-fail` | | PASS | FAIL | PASS | 100.0% | 1 |
| `swift-no-linter` | `swift-no-linter` | | PASS | WARN | PASS | 100.0% | 0 |
| `swift-no-tests` | `swift-no-tests` (no test target) | | PASS | WARN | SKIP | SKIP | 0 |
| `swift-zero-tests` | copy of `swift-no-linter`, `Tests/CalcTests/CalcTests.swift`: `testSum` removed (a test class with no tests) | | PASS | WARN | SKIP | SKIP | 0 |
| `swift-typo-import` | copy of `swift-no-linter`, `Sources/Calc/Calc.swift`: `import Foundaton` added | | FAIL | SKIP | SKIP | SKIP | 1 |
| `swift-old-toolchain` | copy of `swift-no-linter`, `Package.swift`: `swift-tools-version:5.5` → `swift-tools-version:99.0` | | WARN | WARN | WARN | WARN | 0 |
| `swift-missing-deps` | `swift-missing-deps` (depends on a package at `https://invalid.invalid/...`) | | WARN | WARN | WARN | WARN | 0 |
| `swift-swiftlint` | `swift-swiftlint` | swiftlint | PASS | PASS | PASS | 100.0% | 0 |
| `swift-swiftlint-fail` | copy of `swift-swiftlint`, `Sources/Calc/Calc.swift`: `    a + b` → `    return a + b;` | swiftlint | PASS | FAIL | PASS | 100.0% | 1 |
| `swift-swiftformat` | `swift-swiftformat` | swiftformat | PASS | PASS | PASS | 100.0% | 0 |
| `swift-swiftformat-fail` | copy of `swift-swiftformat`, `Sources/Calc/Calc.swift`: `    a + b` → `  a + b` | swiftformat | PASS | FAIL | PASS | 100.0% | 1 |
| `swift-swift-format` | `swift-swift-format` | swift format | PASS | PASS | PASS | 100.0% | 0 |
| `swift-swift-format-fail` | copy of `swift-swift-format`, `Sources/Calc/Calc.swift`: `    a + b` → `  a + b` | swift format | PASS | FAIL | PASS | 100.0% | 1 |

swift-missing-deps runs with `GIT_TERMINAL_PROMPT=0`, so git never waits for input. The `.invalid` host never
resolves, so this is what any offline or blocked download looks like, and no cache on the PC can make it pass.

Report checks:
- **swift-ok**: build `["swift", "build"]`, tests `["swift", "test"]`, coverage
  `["swift", "test", "--enable-code-coverage"]`, all `pass`; the tests output names `Executed 1 test`. Coverage has
  exactly one result: `format` `llvmcov`, `line_pct` 100.0, `branch_pct` null, `source_file` starting `.build/` and
  ending `/debug/codecov/swift-ok.json` (the export was read, not an output percentage). `environment.runners` has a
  `swift` version (not `unknown`). Afterwards the copy holds only the fixture's files plus `.build/` and `.pre-llm/`.
- **swift-build-fail**, **swift-typo-import**: build `fail` (not `dependencies_missing`); lint, tests and coverage
  skipped with reason `build_gate`. swift-typo-import's build output names `no such module 'Foundaton'`.
- **swift-test-fail**: tests `fail`, output names `XCTAssertEqual failed`.
- **swift-lint-fail**: lint command `["swiftc", "-parse", "scripts/Bad.swift"]`, status `fail` (`scripts/` is not part
  of the package).
- **swift-no-tests**, **swift-zero-tests**: tests and coverage both `skipped`, reason `no_tests_found`; project warnings
  do not include `coverage_missing`.
- **swift-old-toolchain**, **swift-missing-deps**: build `dependencies_missing`; project warning
  `dependencies_missing`; no command `fail`. swift-old-toolchain's build output names `99.0`, swift-missing-deps's
  names `invalid.invalid`.
- **swift-swiftlint**: lint command `["swiftlint", "lint", "--quiet"]`, `pass`. **swift-swiftlint-fail**: lint `fail`,
  output names `trailing_semicolon`, and `Sources/Calc/Calc.swift` is byte-for-byte the edited file after the run.
- **swift-swiftformat**: lint command `["swiftformat", "--lint", "."]`, `pass`. **swift-swiftformat-fail**: lint
  `fail`, output names `(indent)`, file unchanged as above.
- **swift-swift-format**: lint command `["swift", "format", "lint", "--strict", "--recursive", "."]`, `pass`.
  **swift-swift-format-fail**: lint `fail`, output names `[Indentation]`, file unchanged as above.

The SwiftLint fixture enables one rule only (`trailing_semicolon`, at error level), so the result does not depend on
the SwiftLint version.

### swift-detect (`--dry-run` only, never needs Swift)

`Package.swift`, `.swiftlint.yml`, `.swiftformat`, `.swift-format`. Expected lines after the project line:

```
  build: swift build  [builtin]
  lint: swiftlint lint --quiet  [config]
  lint: swiftformat --lint .  [config]
  lint: swift format lint --strict --recursive .  [config]
  tests: swift test  [builtin]
  coverage: swift test --enable-code-coverage  [builtin]
```
