# Macro2k Project Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the in-flight Runner exe rename (today's work) and sequence the
highest-value improvements to the Macro2k tool suite — repo hygiene, CI/lint
gates, and the `engine.py` decomposition.

**Architecture:** Part A finishes a half-shipped feature: standalone Runners are
built and distributed as `<Name>-Runner.exe`, and the update feed keeps a
pre-rename `<Name>.exe` copy so installs from before the rename can still
self-update. Part B is a roadmap; each item is scoped to its own future
spec/plan because it changes a subsystem rather than completing one.

**Tech Stack:** Python 3 (stdlib `unittest`), PyInstaller, `gh` CLI, GitHub
Actions (proposed), ruff (proposed).

**Spec:** This document. There is no upstream spec for the rename; the design
is already encoded in `src/runner_update.py`, `packaging/runner_build.spec`,
and `packaging/build.md` (all uncommitted-but-written). Part A makes
`packaging/build_runner.py` agree with them.

## Global Constraints

- Python: use `.venv/Scripts/python.exe`; never a shared interpreter.
- Tests: stdlib only, `python -m unittest discover -s tests -v`. No new test
  framework.
- UI/user-facing strings are **English**, sentence case (docs/TERMINOLOGY.md).
- Runner exe name is exactly `<AppName>-Runner.exe`; the pre-rename name is
  exactly `<AppName>.exe`. Both go through `_sanitize` (`[^A-Za-z0-9_-]` → `_`).
- Don't rename or restructure files that Part B only proposes; Part A touches
  `packaging/build_runner.py` and adds `tests/test_runner_exe_name.py` to git.
- Every task ends green: `python -m unittest discover -s tests` must report
  `OK` (currently 266 tests, 2 errors → 0 after Part A).

## Review Focus

- A Runner built **before** the rename receives a new update zip: it must find
  a file named exactly after its running exe, or it refuses the update.
- `gh` not installed / not logged in: the preflight `--publish` failure path is
  already correct — must stay a clean refusal, not a traceback.
- Two builds at once (Hub + Designer open): each gets an isolated scratch dir;
  a shared zip path or exe name must not clobber the other.
- A display name that `_sanitize` rewrites (`"Brown Dust 2!"` → `Brown_Dust_2`):
  the name written into the zip and the name PyInstaller produced must be the
  same string.
- Project folder name ≠ `flow["name"]`: `appName` (not the folder) drives both
  the exe name and the legacy alias.

---

# Part A — Finish the Runner exe rename (do this now)

The rename is written in the spec, `src/runner_update.py`, and `packaging/build.md`,
and `packaging/build_runner.py` already *produces* `dist/<Name>-Runner/<Name>-Runner.exe`
via `name=f"{APP_NAME}-Runner"`. Two things are missing, both pinned by the
new, untracked `tests/test_runner_exe_name.py`:

1. `build_runner` has no `runner_exe_name()` helper (the test imports it).
2. `_zip_runner()` takes 2 args; it needs a 3rd (`legacy_app_name`) so an update
   zip also carries `<Name>.exe` for pre-rename installs.

### Task 1: `runner_exe_name()` in the build script

**Files:**
- Modify: `packaging/build_runner.py` (near `_sanitize`)
- Test: `tests/test_runner_exe_name.py:16`

**Interfaces:**
- Consumes: `_sanitize(raw: str) -> str` (existing).
- Produces: `runner_exe_name(app_name: str) -> str` → `"<AppName>-Runner.exe"`.

- [ ] **Step 1: Run the failing test**

Run: `.venv/Scripts/python.exe -m unittest tests.test_runner_exe_name -v`
Expected: `AttributeError: module 'build_runner' has no attribute 'runner_exe_name'`

- [ ] **Step 2: Add the helper**

In `packaging/build_runner.py`, immediately after `_sanitize`:

```python
def runner_exe_name(app_name: str) -> str:
    """``<AppName>-Runner.exe`` — the exe ``runner_build.spec`` names.

    The game's name alone reads like the game itself; the ``-Runner`` suffix
    says which window a player is looking at. Must stay in step with the spec's
    ``EXE(name=f"{APP_NAME}-Runner")`` and ``src.runner_update.runner_exe_name``.
    """
    return f"{_sanitize(app_name)}-Runner.exe"
```

- [ ] **Step 3: Re-run the test**

Run: `.venv/Scripts/python.exe -m unittest tests.test_runner_exe_name -v`
Expected: 3 of 4 pass; `test_update_zip_also_carries_the_pre_rename_exe` still
fails with `TypeError: _zip_runner() takes 2 positional arguments but 3 were given`.

### Task 2: Update zips carry the pre-rename exe name

**Files:**
- Modify: `packaging/build_runner.py:815` (`_zip_runner`), `packaging/build_runner.py:981` (`publish`)
- Test: `tests/test_runner_exe_name.py:20`

**Interfaces:**
- Consumes: `runner_exe_name(app_name) -> str` (Task 1), `USER_DIRS` (existing).
- Produces: `_zip_runner(folder: str, zip_path: str, legacy_app_name: str = "") -> None`.

- [ ] **Step 1: Run the failing test**

Run: `.venv/Scripts/python.exe -m unittest tests.test_runner_exe_name -v`
Expected: `TypeError: _zip_runner() takes 2 positional arguments but 3 were given`.

- [ ] **Step 2: Implement the legacy copy**

Replace `_zip_runner` with:

```python
def _zip_runner(folder: str, zip_path: str, legacy_app_name: str = "") -> None:
    """Zip the Runner folder's contents (not the folder itself) for an update.

    When *legacy_app_name* is given, also add a copy of the built exe under the
    pre-rename ``<AppName>.exe`` name. A Runner built before the rename refuses
    an update package that lacks its own exe name (see
    ``src.runner_update.apply``), so every published zip carries both.
    """
    canonical = runner_exe_name(legacy_app_name) if legacy_app_name else ""
    canonical_path = os.path.join(folder, canonical) if canonical else ""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(folder):
            rel_root = os.path.relpath(root, folder)
            if rel_root == ".":
                dirs[:] = [d for d in dirs if d not in USER_DIRS]
            for name in files:
                path = os.path.join(root, name)
                zf.write(path, os.path.relpath(path, folder))
        if canonical_path and os.path.isfile(canonical_path):
            zf.write(canonical_path, f"{_sanitize(legacy_app_name)}.exe")
```

- [ ] **Step 3: Pass the app name from `publish`**

In `publish()`, change the call at line ~981 from:

```python
    _zip_runner(final, zip_path)
```

to:

```python
    _zip_runner(final, zip_path, app_name)
```

- [ ] **Step 4: Run the test**

Run: `.venv/Scripts/python.exe -m unittest tests.test_runner_exe_name -v`
Expected: 4 tests, `OK`.

**Review-focus test to add here** (the sanitised-name case, in the same test file):

```python
    def test_zip_name_matches_a_sanitised_app_name(self):
        tmp = tempfile.mkdtemp(prefix="m2k_exe_")
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        folder = os.path.join(tmp, "Runner")
        os.makedirs(folder)
        with open(os.path.join(folder, "Brown_Dust_2-Runner.exe"), "wb") as fh:
            fh.write(b"MZ")
        zip_path = os.path.join(tmp, "u.zip")
        br._zip_runner(folder, zip_path, "Brown Dust 2!")
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        self.assertIn("Brown_Dust_2-Runner.exe", names)
        self.assertIn("Brown_Dust_2.exe", names)
```

Run: `.venv/Scripts/python.exe -m unittest tests.test_runner_exe_name -v` → `OK`.

### Task 3: Full suite green + commit the rename

**Files:**
- Commit: `packaging/build_runner.py`, `packaging/runner_build.spec`,
  `packaging/entry_runner_single.py`, `src/runner_update.py`,
  `tests/test_runner_exe_name.py`, `packaging/build.md`,
  `apps/workflow_runner.py`, `apps/web/runner/{index.html,js/runner.js,css/runner.css}`,
  `tests/test_runner_logging.py`, `tests/test_runner_source_label.cjs`,
  `tests/test_runner_ui_structure.py`

- [ ] **Step 1: Whole suite**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests`
Expected: `Ran 266 tests ... OK` (0 failures, 0 errors).

- [ ] **Step 2: Compile check (source + packaging)**

Run: `.venv/Scripts/python.exe -m compileall -q src apps packaging`
Expected: no output.

- [ ] **Step 3: Commit in two logical commits**

```bash
git add packaging/build_runner.py packaging/runner_build.spec packaging/entry_runner_single.py \
        src/runner_update.py tests/test_runner_exe_name.py packaging/build.md
git commit -m "feat(runner): ship standalone runners as <Name>-Runner.exe

Keep a legacy <Name>.exe copy in update zips and hand over at startup so
installs from before the rename still self-update."

git add apps/workflow_runner.py apps/web/runner tests/test_runner_logging.py \
        tests/test_runner_source_label.cjs tests/test_runner_ui_structure.py
git commit -m "feat(runner): title the window <Workflow> Runner, tighten log header"
```

- [ ] **Step 4: Push**

Run: `git push origin main`
Expected: both commits on `origin/main` (HEAD was already in sync, 0 ahead/0 behind).

---

# Part B — Improvement roadmap

Each item below needs its own spec/plan before code. They are ordered by
value-per-risk; do them top to bottom, but nothing here blocks anything else.

## B1 — Repo hygiene (30 min, zero risk)

The working tree is ascattered after the rename work. Fix it before branching
for B2/B3 so the baseline is clean.

Concrete actions:

- Prune the three dead worktrees and their branches:
  ```bash
  git worktree prune
  git branch -D worktree-agent-a041d11122e0b9cbe \
                 worktree-agent-a3f81636a3622e0a1 \
                 worktree-agent-ac10f6f29d1646896
  ```
  They point at `1da9a60` and are unreachable from anything; `.claude/worktrees/*`
  entries also show as deleted in `git status`.
- Delete the one unreferenced template:
  `workflows/BrownDust2/templates/crop_20260929_192220_1791_86_15_17.png`
  (grep shows it in no JSON). The other three untracked crops **are** referenced
  by `workflow.json` — `git add` them.
- Commit the BrownDust2 workflow tuning (node positions, template lists, `delay`
  fields, `matchBy: exe`) as its own commit so the diff stops polluting `git status`.
- Remove the stray root `nul` file (already gitignored, but it is a real 10 KB
  file from a `cmd > nul` redirect under bash).
- Retire the stale branches `ao/adb-auto-gam-orchestrator` (Jul 17) and
  `ao/macro2k-orchestrator` (Sep 14) if their content lives on `main`; otherwise
  rebase and open a PR.
- Rename `workflows/z/` if it is a scratch project (it holds a 4 KB workflow and
  no assets). Confirm with the operator before deleting.

Acceptance: `git status` shows only intentional, in-progress work. No orphan
binaries. `git worktree list` shows one worktree.

## B2 — CI gate on GitHub Actions (1–2 h, low risk, high value)

There is no `.github/` at all. The suite is 266 tests in ~7 s and already
stdlib-only, so this is a small YAML file with a large payoff: the rename bug
(Task 1/2) would have been caught the moment the test was pushed.

Proposed `.github/workflows/ci.yml`:

- Trigger: `push` to `main`, `pull_request`.
- Job matrix: `windows-latest` only (tests touch `win32`/`adb` code paths and
  `subprocess`); add `ubuntu-latest` later only for the pure-Python subset.
- Steps: checkout, `actions/setup-python@v5` (3.11), `pip install -r requirements.txt`,
  `python -m unittest discover -s tests -v`, `python -m compileall -q src apps packaging`,
  and Node syntax check (`node --check` over `apps/web/**/*.js`) plus
  `node --test tests/test_designer_geometry.cjs`.
- Cache pip; keep the run under 5 min.

Needs a spec decision: which optional deps (Pillow, onnxruntime, PyAV) CI must
install so the tests that import them run rather than skip.

## B3 — Lint/format gate with ruff (1 h, low risk)

`ruff` has been run here (`.ruff_cache/0.16.3` exists) but there is **no
config file** anywhere, so rules change with each ruff release. Add a
`pyproject.toml` with `[tool.ruff]` (`line-length = 100`, `target-version = "py311"`,
a curated `select`), run `ruff format` once in a dedicated commit, then add
`ruff check .` to B2's CI job.

Sequence: add config → `ruff check` (expect a large baseline) → fix or
`per-file-ignores` → `ruff format --check` → CI gate.

## B4 — Break up `src/workflow/engine.py` (days, medium risk)

`engine.py` is **5846 lines / 233 functions**; node execution is a single long
`if ntype == …` chain (lines ~2552–2974, ~5707). It is the single biggest
maintainability drag and the file most likely to cause a merge conflict or a
missed branch. `apps/workflow_designer.py` (2764) and the `apps/web/wf` JS
(~14k lines) are the same shape but lower risk.

Safe incremental approach (needs its own spec):

1. Introduce `src/workflow/nodes/` with one module per node family
   (image, text, control-flow, win32, emulator, variables) and a
   `NODE_HANDLERS: dict[str, Callable]` registry. **Do not change behavior.**
2. Move one family at a time into `nodes/<family>.py`; the engine looks up
   `NODE_HANDLERS[ntype]` and falls back to the old chain until the chain is empty.
3. The existing suite is the safety net, but it does not cover every node type;
   before moving a family, add a characterization test per node type in it
   (record params → assert the same engine call/result as the old code path).
4. Delete the dead `if` branches only after the family's tests pass.

`NODE_TYPES` (line 111) already describes every node; it and the JSON corpus
(`workflows/*/*.json`, ~45 distinct types) are the inventory to work from.

## B5 — Reproducible builds (half day, low risk)

`requirements.txt` uses `>=` for everything and there is no lock. PyInstaller
output therefore differs between the Hub's interpreter and a fresh checkout.
Add a pinned `requirements.lock` (via `pip freeze` on the build machine) and
have `packaging/build.ps1` / `build_runner.py` document that builds use it.
Optional: a `pyproject.toml` with extras so `pip install -e .[build]` is the
one install path.

## B6 — Docs sync (2 h, low risk)

- `README.md` still describes only the suite's frozen modes; add the per-game
  `dist/<Name>-Runner/<Name>-Runner.exe` build (the detail already exists in
  `packaging/build.md`).
- `AGENTS.MD` is a verbatim copy of the assistant operating spec and occupies
  the repo root; move it to `docs/` or point it at the canonical copy so it
  doesn't drift.
- `docs/superpowers/plans/` has three completed plans; add a short `README` or
  index so the live plan (this one) is findable.

## B7 — Close the test-coverage gaps (ongoing)

The suite is broad (~266 tests) but per-node. Add tests for the paths most
likely to break silently: the `runner_update.apply` failure modes (corrupt zip,
missing exe, timeout at `UPLOAD_TIMEOUT`), and the preflight `--publish` refusal
paths when `gh` is absent or unauthenticated. These are cheap, deterministic,
and directly under the rename change made today.

---

## Self-review

- **Spec coverage:** the rename design (spec file, `runner_update`, `build.md`)
  is fully implemented by Part A Tasks 1–2; Task 3 lands it. B1–B7 are scoped
  separately and intentionally not implemented here.
- **Placeholder scan:** Part A has exact code and exact commands; Part B items
  name the files, the change, and the acceptance test.
- **Type consistency:** `runner_exe_name(app_name: str) -> str` in
  `build_runner` vs `runner_update.runner_exe_name(info: dict) -> str` are
  deliberately different signatures (build-time app name vs runtime build info);
  the test file pins both.
- **Review focus:** the pre-rename-updater case is Task 2; the sanitised-name
  case is the added test in Task 2; `gh`-absent and concurrent-build cases are
  already covered by `preflight()`/`_make_build_scratch()` and are noted for B7.
