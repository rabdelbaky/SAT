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

