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
| `services/ml`                   | python     | `pyproject.toml`     | `["pyproject.toml", "requirements.txt"]`  | true     |
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

**--dry-run output** (one line per project, format: `<path>  <language>  <build_files>  [untested]`;
the `[untested]` suffix is left off for a tested language):

```
.  javascript  package.json
packages/api  javascript  package.json
packages/ui  javascript  package.json
services/ml  python  pyproject.toml, requirements.txt
services/worker  go  go.mod  [untested]
```

*(Python is tested since Session 10, JavaScript since Session 11 and Java since Session 12; the others are `[untested]`
until their fixtures pass; exact whitespace may vary.)*

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
copied to a temp folder and run with `--path <copy>`; the project is `.`, language `kotlin [untested]`.

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
