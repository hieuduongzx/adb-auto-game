# Runner Changelog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authored GitHub Release changelogs to standalone game Runners, preserve them across updates, show an eligible release once after a successful update, and expose a safe manual changelog history.

**Architecture:** Workflow Hub collects Markdown and an auto-show policy, transports the text through a temporary UTF-8 file, and `packaging/build_runner.py` publishes a metadata-bearing GitHub Release body through `gh --notes-file`. `src/runner_update.py` becomes the single normalization and durable-state boundary for matching releases, cache, and pending announcements; `WorkflowRunnerAPI` maps that state and the per-Runner preference to a narrow frontend API. The Runner UI renders a deliberately small Markdown grammar with DOM nodes and `textContent`, never release-controlled `innerHTML`.

**Tech Stack:** Python 3.10+, standard library (`json`, `tempfile`, `urllib`, `unittest`/`unittest.mock`), PyWebView, vanilla JavaScript/HTML/CSS, Node.js built-in test runner, GitHub CLI, PyInstaller

**Spec:** `docs/superpowers/specs/2026-09-22-runner-changelog-design.md`

## Global Constraints

- Scope is standalone game Runners built and published from Workflow Hub; do not change the Macro2k suite updater or Designer-only local builds.
- GitHub Releases are the canonical changelog source; include only non-draft releases whose tag starts with the bundled Runner `tagPrefix`.
- Empty changelogs never block build or publish; use `Standalone Runner for <display name>, version <version>.` and force automatic display off when no changelog was supplied.
- Release metadata uses exactly `<!-- macro2k-runner: {"autoShow":true} -->` (or `false`) and unknown or malformed metadata defaults to automatic display disabled.
- Transport multiline Markdown from Hub to packaging through a temporary UTF-8 notes file, never as command-line text; `gh release create` must receive a notes file through `--notes-file`.
- Persist changelog cache and pending announcement per Runner under preserved `data/`; every JSON write uses a temporary sibling followed by `os.replace`.
- Write pending state only after the selected release and downloaded package are validated and immediately before update handoff; display it only when its target version equals bundled `runner_build.json.version`.
- Network, GitHub API, metadata, cache, or pending-state failures must not block builds, Runner startup, update checks, or cached/manual history.
- Automatic display additionally requires non-empty Markdown, release `autoShow`, the user preference (default enabled), and a version not previously automatically shown; closing the automatic dialog records that version and clears matching pending state.
- Manual changelog history remains available regardless of the automatic-display preference and is sorted newest first.
- Render only headings, paragraphs, ordered/unordered lists, emphasis, inline code, fenced code blocks, block quotes, and HTTPS links; raw HTML is text/discarded, release text is never assigned through `innerHTML`, and links use a validated backend external-link API.
- Add no runtime dependency; release parsing, state, and Markdown rendering remain standard-library/vanilla-JavaScript implementations.
- Preserve current build, Runner UI, update, Python, and JavaScript behavior outside this feature.

## File Map

- Modify `apps/web/hub/js/hub.js`: authoring controls, automatic switch behavior, and expanded `build_runner` call.
- Modify `apps/web/hub/css/hub.css`: build-dialog textarea and auto-show switch layout.
- Modify `apps/workflow_hub.py`: validate changelog inputs, own the temporary notes file for the subprocess lifetime, pass exact workflow path, and clean up.
- Modify `packaging/build_runner.py`: read notes, encode metadata, publish via `--notes-file`, and persist version through the resolved workflow path.
- Modify `src/runner_update.py`: normalize release history, parse metadata, atomically cache history/pending state, and preserve the selected release through update handoff.
- Modify `apps/workflow_runner.py`: expose changelog payload/refresh/acknowledgement/preference APIs and validated HTTPS external opening.
- Modify `apps/web/runner/index.html`: add desktop/mobile Changelog navigation, history pane, post-update dialog host, and preference control.
- Modify `apps/web/runner/js/runner.js`: changelog state, safe Markdown renderer, history selection, refresh, preference, manual links, and one-time automatic dialog.
- Modify `apps/web/runner/css/runner.css`: responsive changelog list/content/dialog styles.
- Create `tests/test_workflow_hub_build.py`: Hub validation, argument transport, notes-file lifetime/cleanup, and exact `--flow-path` coverage.
- Extend `tests/test_build_publish.py`: encoded body, `--notes-file`, fallback body, and resolved version persistence.
- Create `tests/test_runner_update.py`: normalization/filtering, malformed metadata, atomic state, cache fallback/refresh, pending timing, and version gating.
- Create `tests/test_runner_changelog_api.py`: backend payload, preference, acknowledgement, and safe-link API.
- Create `tests/test_runner_changelog_ui.cjs`: Hub switch behavior plus Runner safe Markdown/history/show-once behavior.
- Modify `tests/test_hub_ui.py`: run the new Node UI contract from the normal Python suite.
- Modify `tests/test_runner_ui_structure.py`: assert Changelog tab/pane, preference, and accessible dialog structure.

---

### Task 1: Define release metadata and publish through a notes file

**Files:**
- Modify: `packaging/build_runner.py:914-961,983-987,1171-1176,1190-1228`
- Test: `tests/test_build_publish.py:70-121`

**Interfaces:**
- Consumes: optional UTF-8 file path from future Hub Task 3 and boolean `auto_show`.
- Produces: `compose_release_notes(display_name: str, version: str, notes_file: str = "", auto_show: bool = False) -> str`; `publish(..., notes_file: str = "", auto_show: bool = False, dry_run: bool = False) -> str`; CLI flags `--notes-file PATH` and `--auto-show`.
- Release body invariant: first line is compact JSON metadata; body after the separating blank line is authored Markdown or the existing fallback sentence.

- [ ] **Step 1: Add failing publish-body tests**

Add these cases to `TestPublish`; capture `_gh` arguments and read the generated notes file inside the `_gh` side effect while it still exists:

```python
def test_publish_uses_notes_file_with_metadata_and_markdown(self):
    authored = Path(self.tmp) / "authored.md"
    authored.write_text("## Changes\n\n- Added **fast mode**.\n", encoding="utf-8")
    seen = {}

    def gh_side_effect(args, **kwargs):
        notes_path = args[args.index("--notes-file") + 1]
        seen["path"] = notes_path
        seen["body"] = Path(notes_path).read_text(encoding="utf-8")
        return _ok()

    with mock.patch.object(br, "publish_checks", return_value=[]), \
         mock.patch.object(br, "_gh", side_effect=gh_side_effect), \
         mock.patch.object(br, "log"), mock.patch.object(br, "progress"):
        br.publish(self.final, "Game", "Game", "1.0.22", "o/r",
                   notes_file=str(authored), auto_show=True)

    self.assertEqual(
        seen["body"],
        '<!-- macro2k-runner: {"autoShow":true} -->\n\n'
        '## Changes\n\n- Added **fast mode**.\n',
    )
    self.assertFalse(os.path.exists(seen["path"]))
```

Also add `test_empty_notes_use_fallback_and_disable_auto_show`, invoking `compose_release_notes("Game", "1.0.22", "", True)` and asserting the exact false metadata plus `Standalone Runner for Game, version 1.0.22.`. Assert the `release create` args contain `--notes-file` and do not contain `--notes`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_build_publish.TestPublish -v`

Expected: FAIL because `publish` has no `notes_file`/`auto_show` parameters and still emits `--notes`.

- [ ] **Step 3: Implement release-body composition and temporary publish file**

Add the following boundary and thread the new arguments through `build()` and `main()`:

```python
def compose_release_notes(display_name: str, version: str,
                          notes_file: str = "", auto_show: bool = False) -> str:
    markdown = ""
    if notes_file:
        with open(notes_file, "r", encoding="utf-8") as fh:
            markdown = fh.read()
    if not markdown.strip():
        markdown = f"Standalone Runner for {display_name}, version {version}."
        auto_show = False
    metadata = json.dumps({"autoShow": bool(auto_show)}, separators=(",", ":"))
    return f"<!-- macro2k-runner: {metadata} -->\n\n{markdown.rstrip()}\n"
```

Inside `publish`, create a `NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md", delete=False)`, write `compose_release_notes(...)`, call `_gh([... "--notes-file", publish_notes, ...])`, and unlink `publish_notes` in `finally`. Keep timeout and error recovery unchanged. Extend `build(..., notes_file: str = "", auto_show: bool = False)` and pass both to `publish`; add parser flags:

```python
ap.add_argument("--notes-file", default="",
                help="UTF-8 Markdown body for the GitHub Release.")
ap.add_argument("--auto-show", action="store_true",
                help="Allow this non-empty changelog to open once after update.")
```

- [ ] **Step 4: Verify publish behavior GREEN**

Run: `.venv\Scripts\python.exe -m unittest tests.test_build_publish.TestPublish -v`

Expected: all `TestPublish` cases PASS, including existing long-timeout and recovery assertions.

- [ ] **Step 5: Commit the publishing unit**

```powershell
git add packaging/build_runner.py tests/test_build_publish.py
git commit -m "feat: publish runner changelog notes"
```

### Task 2: Fix successful-build version persistence against the resolved workflow

**Files:**
- Modify: `packaging/build_runner.py:983-1005,1171-1177`
- Test: `tests/test_build_publish.py`

**Interfaces:**
- Consumes: `resolved: str` returned by existing `resolve_flow_path(workflow_dir, flow_path)`.
- Produces: successful `build(..., save_version=True)` always calls `_save_version(resolved, version, repo)`; no call uses the possibly empty raw `flow_path`.

- [ ] **Step 1: Add the failing persistence regression**

Add a source-contract test that parses the `build` function AST, finds `_save_version`, and pins its first argument to `resolved` (this isolates the defect without running PyInstaller):

```python
def test_build_saves_version_to_resolved_workflow(self):
    source = Path(br.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    build_fn = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "build")
    calls = [n for n in ast.walk(build_fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_save_version"]
    self.assertEqual(len(calls), 1)
    self.assertIsInstance(calls[0].args[0], ast.Name)
    self.assertEqual(calls[0].args[0].id, "resolved")
```

Import `ast` at the test file top.

- [ ] **Step 2: Verify the regression is RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_build_publish.TestVersionPersistence -v`

Expected: FAIL because the current call is `_save_version(flow_path, version, repo)`.

- [ ] **Step 3: Apply the one-line persistence fix**

```python
if save_version:
    _save_version(resolved, version, repo)
```

- [ ] **Step 4: Verify persistence and publish tests GREEN**

Run: `.venv\Scripts\python.exe -m unittest tests.test_build_publish -v`

Expected: PASS.

- [ ] **Step 5: Commit the persistence fix**

```powershell
git add packaging/build_runner.py tests/test_build_publish.py
git commit -m "fix: persist runner version to resolved workflow"
```

### Task 3: Transport Hub changelog values and keep the notes file alive

**Files:**
- Create: `tests/test_workflow_hub_build.py`
- Modify: `apps/workflow_hub.py:553-594,650-715`

**Interfaces:**
- Consumes: `WorkflowHubAPI.build_runner(path: str, version: str = "", publish: bool = False, repo: str = "", changelog: str = "", auto_show: bool = False, dry_run: bool = False) -> dict`.
- Produces: `_build_worker(info, version, publish, repo, changelog, auto_show, dry_run) -> None`; subprocess arguments include `--flow-path <info["path"]>` always, and include `--notes-file <temp path>` plus optional `--auto-show` only when publishing/dry-running a non-empty changelog.
- Validation: reject changelog values that are not strings and UTF-8 bodies larger than 125,000 bytes; normalize whitespace-only text to empty and force `auto_show=False` for empty text.

- [ ] **Step 1: Write failing Hub API validation and transport tests**

Instantiate `WorkflowHubAPI`, patch `build_info` to return a valid literal payload, patch `threading.Thread` so `.start()` invokes the target synchronously, and patch `subprocess.Popen` with a fake process whose constructor records the command and asserts the path following `--notes-file` exists with exact UTF-8 content. The fake `stdout` is an empty iterable, `wait()` returns `1` (avoiding unrelated success handling), and after `build_runner` returns assert the temp path no longer exists.

Use these assertions:

```python
self.assertIn("--flow-path", command)
self.assertEqual(command[command.index("--flow-path") + 1], self.flow_path)
self.assertNotIn("## Changes", command)
self.assertEqual(Path(notes_path).read_text("utf-8"), "## Changes\n\n- Café ✓\n")
self.assertIn("--auto-show", command)
```

Add independent tests that `changelog=object()` returns `{"ok": False, ...}`, a 125,001-byte ASCII changelog is rejected, empty text starts the build without `--notes-file`/`--auto-show`, and a Popen exception still removes the temporary file.

- [ ] **Step 2: Run Hub tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_workflow_hub_build -v`

Expected: FAIL because `build_runner` does not accept changelog inputs, does not pass `--flow-path`, and creates no notes file.

- [ ] **Step 3: Implement validation and worker-owned file lifetime**

At the API boundary:

```python
if not isinstance(changelog, str):
    return {"ok": False, "error": "Changelog must be Markdown text"}
if len(changelog.encode("utf-8")) > 125_000:
    return {"ok": False, "error": "Changelog must be 125,000 UTF-8 bytes or less"}
changelog = changelog if changelog.strip() else ""
auto_show = bool(auto_show) if changelog else False
```

Store neither release text nor the temporary path in `_build` state. Pass normalized values to `_build_worker`. In `_build_worker`, add `"--flow-path", info["path"]` to `cmd`; for a publish/dry-run with changelog, create a named UTF-8 file, append `--notes-file` and its path, append `--auto-show` only when true, launch/wait exactly as today, and unlink in the worker's outer `finally` after stdout has closed/process has ended.

- [ ] **Step 4: Verify Hub transport GREEN**

Run: `.venv\Scripts\python.exe -m unittest tests.test_workflow_hub_build -v`

Expected: PASS, proving content is off the command line, alive at Popen, and removed on success/failure.

- [ ] **Step 5: Commit the Hub backend transport**

```powershell
git add apps/workflow_hub.py tests/test_workflow_hub_build.py
git commit -m "feat: transport runner changelog from hub"
```

### Task 4: Add changelog authoring to the Hub build dialog

**Files:**
- Modify: `apps/web/hub/js/hub.js:554-625`
- Modify: `apps/web/hub/css/hub.css:397-412`
- Create: `tests/test_runner_changelog_ui.cjs`
- Modify: `tests/test_hub_ui.py:11-22`

**Interfaces:**
- Consumes: Hub API signature from Task 3.
- Produces: `promptBuild(info) -> Promise<{version: string, publish: boolean, repo: string, changelog: string, autoShow: boolean} | null>` and `syncChangelogAutoShow(textarea, checkbox, previousNonEmpty) -> boolean` (returns new non-empty state for deterministic testing).

- [ ] **Step 1: Add failing Hub dialog behavior tests**

Load `hub.js` in a Node `vm` with `document.readyState="loading"`. Exercise the pure transition helper and assert:

```javascript
assert.equal(ctx.syncChangelogAutoShow(textarea(""), checkbox(false), false), false);
const cb = checkbox(false);
assert.equal(ctx.syncChangelogAutoShow(textarea("## Added"), cb, false), true);
assert.equal(cb.checked, true);
cb.checked = false; // publisher override while still non-empty
ctx.syncChangelogAutoShow(textarea("## Edited"), cb, true);
assert.equal(cb.checked, false);
ctx.syncChangelogAutoShow(textarea("   "), cb, true);
assert.equal(cb.checked, false);
```

Also assert source wiring passes `choice.changelog, choice.autoShow` after repo in `a.build_runner(...)`, and dialog markup contains `build-changelog` textarea plus `build-auto-show` checkbox.

Extend `tests/test_hub_ui.py` to run both `test_hub_grid.cjs` and `test_runner_changelog_ui.cjs` as subtests so `unittest discover` includes the JavaScript contract.

- [ ] **Step 2: Run the Node contract and verify RED**

Run: `node --test tests/test_runner_changelog_ui.cjs`

Expected: FAIL because helper and controls do not exist.

- [ ] **Step 3: Implement dialog controls and transition-only defaults**

Add a Markdown textarea shown with publishing controls and this exact transition logic:

```javascript
function syncChangelogAutoShow(textarea, checkbox, wasNonEmpty){
  const nonEmpty = !!String(textarea.value || "").trim();
  if(nonEmpty !== wasNonEmpty) checkbox.checked = nonEmpty;
  checkbox.disabled = !nonEmpty;
  return nonEmpty;
}
```

Initialize `wasNonEmpty=false`, call the helper on each `input`, and keep manual checkbox changes intact while text remains non-empty. Return raw textarea content (backend performs the authoritative trim/limit validation), and call:

```javascript
await a.build_runner(path, choice.version, choice.publish, choice.repo,
                     choice.changelog, choice.autoShow);
```

Style `.build-changelog` with full width, `min-height: 120px`, vertical resize, and the existing form typography; reuse `.build-check` for the auto-show row and hide/disable both authoring controls when Publish is unchecked so local-only builds remain unchanged.

- [ ] **Step 4: Verify Hub UI GREEN**

Run:

```powershell
node --test tests/test_hub_grid.cjs tests/test_runner_changelog_ui.cjs
.venv\Scripts\python.exe -m unittest tests.test_hub_ui -v
node --check apps/web/hub/js/hub.js
```

Expected: all commands PASS.

- [ ] **Step 5: Commit the Hub authoring UI**

```powershell
git add apps/web/hub/js/hub.js apps/web/hub/css/hub.css tests/test_runner_changelog_ui.cjs tests/test_hub_ui.py
git commit -m "feat: author runner changelogs in hub"
```

### Task 5: Normalize releases and implement atomic cache/pending state

**Files:**
- Create: `tests/test_runner_update.py`
- Modify: `src/runner_update.py:18-33,74-129,229-285`

**Interfaces:**
- Produces `normalize_release(release: dict, tag_prefix: str) -> Optional[dict]` with exact public keys `version: str`, `tag: str`, `markdown: str`, `page: str`, `publishedAt: str`, `autoShow: bool`, `url: Optional[str]`, `size: int`, plus private comparison key `numbers: Tuple[int, ...]`.
- Produces `normalize_releases(releases: list, tag_prefix: str) -> list[dict]`, newest version first; draft/wrong-prefix/non-numeric tags are omitted, but matching history entries need not have a zip asset.
- Keeps `latest_release(repo, tag_prefix, releases=None) -> Optional[dict]` compatible: select the newest normalized record that has a zip `url`; `check()` still returns selected `notes` (set from normalized `markdown`) plus `tag`, `publishedAt`, and `autoShow`.
- Produces `state_dir(info: dict) -> str`, `load_cached_history(info) -> list[dict]`, `refresh_history(info, releases: Optional[list] = None) -> list[dict]`, `write_pending(info, release: dict) -> bool`, `pending_announcement(info) -> Optional[dict]`, and `acknowledge_pending(info, version: str) -> bool`.
- State files are `data/runner/<safe-app-name>/changelog-cache.json` and `pending-changelog.json`; persistence excludes `numbers`, `url`, and `size` from history/pending records.

- [ ] **Step 1: Write failing normalization and metadata tests**

Use literal releases containing matching/wrong prefixes, draft entries, absent assets, and this body:

```python
body = '<!-- macro2k-runner: {"autoShow":true} -->\n\n## Changes\n\n- Fast.'
```

Assert metadata is removed from `markdown`, all six public changelog fields match, history includes the matching no-asset release, `latest_release` skips it for update selection, and ordering uses `parse_version` rather than API order. Add absent, `{"autoShow":"yes"}`, invalid JSON, and unrelated HTML-comment cases; each must return `autoShow=False` without raising and leave unrelated comments as Markdown text.

- [ ] **Step 2: Run normalization tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runner_update.ReleaseNormalizationTests -v`

Expected: ERROR because normalization APIs do not exist.

- [ ] **Step 3: Implement strict metadata parsing and normalized selection**

Use a start-of-body metadata pattern that recognizes only the machine comment and strict JSON boolean:

```python
_METADATA_RE = re.compile(
    r"\A\ufeff?[ \t]*<!--\s*macro2k-runner:\s*(\{[^\r\n]*\})\s*-->"
    r"[ \t]*(?:\r?\n)?(?:\r?\n)?",
)

def _release_markdown(body: object) -> tuple[str, bool]:
    text = str(body or "")
    match = _METADATA_RE.match(text)
    auto_show = False
    if match:
        try:
            value = json.loads(match.group(1)).get("autoShow")
            auto_show = value if isinstance(value, bool) else False
        except Exception:
            auto_show = False
        text = text[match.end():]
    return text.strip(), auto_show
```

Build normalized dicts, retain the existing zip lookup, and map selected `markdown` back to `check()["notes"]` so update prompt callers remain compatible.

- [ ] **Step 4: Write failing cache/pending tests**

Patch `runner_update.data_root` to a temporary directory and assert:

- `refresh_history(info, releases)` atomically writes normalized JSON and returns it.
- A later patched `fetch_releases` exception returns the last valid cache.
- Invalid top-level JSON/non-list cache returns `[]`.
- Replacing `os.replace` with a spy sees a sibling `.tmp` source and final JSON destination.
- `write_pending` round-trips a record only when `info["version"]` later equals pending `version`; mismatch and corrupt JSON return `None`.
- `acknowledge_pending(info, other_version)` leaves it intact; matching version atomically replaces it with `{}` and subsequent load returns `None`.

- [ ] **Step 5: Implement state paths and atomic JSON helper**

```python
def _atomic_write_json(path: str, value: object) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
```

Sanitize `appName` with `re.sub(r"[^A-Za-z0-9_.-]+", "_", ...).strip("._") or "Runner"`. Cache only after the complete fetched list normalizes successfully; catch fetch/parse/write failures in `refresh_history`, log, and return `load_cached_history`. Every public state reader catches corrupt/missing content.

- [ ] **Step 6: Persist pending only at validated update handoff**

In `apply`, after `_safe_extract`, zip removal, and expected-executable validation, but immediately before `write_update_script`/subprocess handoff, call:

```python
write_pending(info, {
    "version": found["version"], "tag": found.get("tag", ""),
    "markdown": found.get("notes", ""), "page": found.get("page", ""),
    "publishedAt": found.get("publishedAt", ""),
    "autoShow": bool(found.get("autoShow")),
})
```

Persist even an empty selected changelog so pending state truthfully records the validated update target; the payload's non-empty check still prevents display. If `write_pending` fails, log and continue update handoff. Extend tests by mocking download/extract/Popen/`os._exit`; assert no pending write on download/zip/executable validation failures and exactly one write before Popen on success.

- [ ] **Step 7: Run update tests GREEN**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runner_update -v`

Expected: PASS.

- [ ] **Step 8: Commit the runtime data layer**

```powershell
git add src/runner_update.py tests/test_runner_update.py
git commit -m "feat: cache runner changelog release state"
```

### Task 6: Expose backend changelog state, preference, acknowledgement, and safe links

**Files:**
- Create: `tests/test_runner_changelog_api.py`
- Modify: `apps/workflow_runner.py:174-257,485-532,850-934,1532-1540`

**Interfaces:**
- Consumes: Task 5 state APIs and existing per-Runner `_runner_config` atomic persistence.
- Produces `_changelog_payload(refresh: bool = False) -> dict` with `history: list[dict]`, `pending: Optional[dict]`, `autoShowEnabled: bool`, `shownVersion: str`, `shouldAutoShow: bool`.
- Produces API methods `changelog_refresh() -> dict`, `set_changelog_auto_show(enabled: bool) -> dict`, `acknowledge_changelog(version: str) -> dict`, and `open_external_url(url: str) -> bool`.
- `_runner_payload()` gains `"changelog": <payload>`; default preference is true when `autoShowChangelog` is absent.

- [ ] **Step 1: Write failing payload/show-once tests**

Construct `WorkflowRunnerAPI` via `__new__` to avoid engine threads, assign literal `_runner_info`, `_runner_config`, `_runner_config_path`, and lock, then mock Task 5 calls. Assert `shouldAutoShow` is true only for current-version pending with non-empty Markdown, pending `autoShow=True`, default-enabled preference, and a different `shownChangelogVersion`. Parameterize each false condition, including version mismatch. Assert history remains present when preference is false.

- [ ] **Step 2: Verify payload tests RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runner_changelog_api.RunnerChangelogPayloadTests -v`

Expected: ERROR because `_changelog_payload` is missing.

- [ ] **Step 3: Implement backend payload and refresh**

Load cached history for the initial payload and call `refresh_history` only from `changelog_refresh` and the existing online update-check paths (`_auto_check_update`/`update_check`) so startup remains usable offline. Merge a valid pending record into history by tag/version if the cache does not contain it, then sort by `parse_version(version)` descending. Compute:

```python
should_auto_show = bool(
    pending
    and pending.get("version") == str(self._runner_info.get("version") or "")
    and str(pending.get("markdown") or "").strip()
    and pending.get("autoShow") is True
    and self._runner_config.get("autoShowChangelog", True) is not False
    and str(self._runner_config.get("shownChangelogVersion") or "") != pending.get("version")
)
```

Do not clear a mismatched pending marker at startup: it remains inert and can diagnose/complete a later successful relaunch.

- [ ] **Step 4: Write failing mutation and safe-link tests**

Assert `set_changelog_auto_show(False)` writes `autoShowChangelog=False` through `_save_runner_config` and still returns history. Assert `acknowledge_changelog("1.2.0")` records `shownChangelogVersion`, calls `runner_update.acknowledge_pending(info, "1.2.0")`, and returns `shouldAutoShow=False`; empty/other versions do not acknowledge current pending. Patch `webbrowser.open` and assert only absolute `https://` URLs with a hostname are opened; reject `http:`, `javascript:`, `file:`, protocol-relative URLs, and URLs containing username/password.

- [ ] **Step 5: Implement mutation and validated external opening**

Use `urllib.parse.urlparse`; accept exactly `scheme == "https"`, non-empty `hostname`, and `username is password is None`. Keep browser opening in try/except. Preference and shown-version writes stay under `_runner_config_lock` and use existing `_save_runner_config`, which already writes a temporary sibling and `os.replace`.

- [ ] **Step 6: Verify backend API GREEN**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runner_changelog_api tests.test_runner_update -v`

Expected: PASS.

- [ ] **Step 7: Commit the backend API**

```powershell
git add apps/workflow_runner.py tests/test_runner_changelog_api.py
git commit -m "feat: expose runner changelog state"
```

### Task 7: Build the safe Markdown renderer and changelog interactions

**Files:**
- Modify: `apps/web/runner/js/runner.js:1-30,267-330,1375-1423,1425-1524,1697-1730`
- Extend: `tests/test_runner_changelog_ui.cjs`

**Interfaces:**
- Consumes backend shape from Task 6.
- Produces `renderSafeMarkdown(markdown: string, root: Element) -> void`; `applyChangelog(payload: object) -> void`; `selectChangelog(version: string) -> void`; `showChangelog(version?: string) -> void`; `maybeShowPendingChangelog() -> Promise<void>`; `onChangelogRefresh()`, `onChangelogAutoShow(enabled)`, and `openChangelogLink(url)`.
- Renderer link contract: create `<a href="...">` only when `new URL(target).protocol === "https:"`; click prevents navigation and calls `api().open_external_url(href)`.

- [ ] **Step 1: Add failing safe-renderer tests**

In the Node test, provide a minimal fake DOM (`createElement`, `createTextNode`, `appendChild`, attributes, listeners) and call `renderSafeMarkdown` with headings, paragraph emphasis, ordered/unordered lists, inline/fenced code, quote, raw `<img onerror=...>`, an HTTPS link, and `javascript:`/`file:` links. Walk the created nodes and assert:

```javascript
assert.equal(serialized.includes('innerHTML'), false);
assert.equal(findTags(root, 'script').length, 0);
assert.equal(findTags(root, 'img').length, 0);
assert.equal(findTags(root, 'a').length, 1);
assert.equal(findTags(root, 'a')[0].href, 'https://github.com/o/r/releases/tag/x');
assert.match(root.textContent, /<img onerror=alert\(1\)>/);
assert.match(root.textContent, /unsafe/); // unsafe link label remains text
```

Add source guard `assert.doesNotMatch(rendererSource, /\.innerHTML\s*=/)` scoped from `function renderSafeMarkdown` to `function applyChangelog`.

- [ ] **Step 2: Run renderer tests and verify RED**

Run: `node --test tests/test_runner_changelog_ui.cjs`

Expected: FAIL because the renderer does not exist.

- [ ] **Step 3: Implement a line/block parser and text-only inline parser**

Implement block parsing for `^#{1,6} `, fenced triple-backtick blocks, `^> ` quotes, `^[-*+] ` lists, `^\d+[.)] ` lists, blank-line paragraph boundaries, and ordinary paragraphs. Inline parsing recognizes backtick code, `**strong**`/`__strong__`, `*em*`/`_em_`, and `[label](URL)`; every unmatched token is appended with `document.createTextNode`. Never parse HTML and never assign Markdown-derived strings to `innerHTML`. Unsafe links append only their label text.

- [ ] **Step 4: Add failing history/show-once interaction tests**

Use a fake backend and payload with versions `1.2.0`, `1.1.0`; assert newest selection, selecting older content, refresh calls `changelog_refresh`, preference calls `set_changelog_auto_show`, and manual opening never calls `acknowledge_changelog`. For `shouldAutoShow=true`, assert `maybeShowPendingChangelog` opens exactly one `uiDialog` with a DOM body callback and acknowledges only after the promise resolves/close; invoking it again for the same version in-session does not reopen.

- [ ] **Step 5: Extend `uiDialog` for safe DOM content and implement interactions**

Add an optional `spec.body(bd)` callback; when present, do not construct the message paragraph, allowing the dialog to append the already-safe Markdown DOM. Track `_autoChangelogFor` by version. `applyChangelog` copies arrays/records defensively, keeps current selection if present, otherwise selects index 0, and renders empty states. Call `maybeShowPendingChangelog()` after `applyRunnerInfo(st.runner)` in `init`; update `applyRunnerInfo` to call `applyChangelog(r.changelog || {})` before update rendering.

- [ ] **Step 6: Verify JavaScript behavior GREEN**

Run:

```powershell
node --test tests/test_runner_changelog_ui.cjs
node --check apps/web/runner/js/runner.js
```

Expected: PASS.

- [ ] **Step 7: Commit the safe renderer and behavior**

```powershell
git add apps/web/runner/js/runner.js tests/test_runner_changelog_ui.cjs
git commit -m "feat: render safe runner changelog markdown"
```

### Task 8: Add responsive Changelog navigation, history pane, dialog, and preference UI

**Files:**
- Modify: `apps/web/runner/index.html:68-175,253-269`
- Modify: `apps/web/runner/css/runner.css:262-310,370-440,480-521`
- Modify: `apps/web/runner/js/runner.js:267-330`
- Modify: `tests/test_runner_ui_structure.py:48-89`

**Interfaces:**
- Consumes Task 7 handlers and renderer.
- Produces IDs `rtab-btn-changelog`, `r-changelog`, `changelog-list`, `changelog-title`, `changelog-date`, `changelog-body`, `changelog-empty`, `btn-changelog-refresh`, `btn-changelog-release`, and `changelog-auto-show`; mobile view value `changelog`.

- [ ] **Step 1: Add failing HTML structure/accessibility tests**

Assert desktop right tabs are `Activity`, `Log`, `Changelog`, `Settings`; the Changelog tab controls `r-changelog`; the pane has a version-list region and article; refresh/release buttons are real buttons; the preference is a checkbox with label text exactly `Automatically show changelog after updates`; the body is not an HTML string container; and mobile tabs include `Changelog` with `data-mobile-view="changelog"`.

- [ ] **Step 2: Run structure tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runner_ui_structure -v`

Expected: FAIL because the tab, pane, controls, and preference do not exist.

- [ ] **Step 3: Add semantic markup and navigation wiring**

Add Changelog between Log and Settings in both navs. The pane uses a listbox-like version column (`role="list"`, buttons with `aria-current`) and an `<article>` content column. Put the preference in Settings immediately below Updates, enabled by default in markup and synchronized from backend payload. Extend `switchMobileView` allowed values and panel mapping with `changelog`; update the narrow CSS selectors so exactly that pane appears.

- [ ] **Step 4: Add responsive, theme-token-only styling**

Use existing `--panel`, `--surface`, `--line`, `--ink`, `--muted`, `--accent`, spacing, and radius tokens. Desktop pane is `grid-template-columns: minmax(110px, .32fr) minmax(0, 1fr)`; version list and article independently scroll. At `max-width: 640px`, use one column with a horizontal version strip above content. Style Markdown descendants (`h1`-`h6`, `p`, `ul`, `ol`, `blockquote`, `code`, `pre`, `a`) without permitting overflow; fenced code scrolls horizontally.

- [ ] **Step 5: Verify structure and UI contracts GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_runner_ui_structure tests.test_hub_ui -v
node --test tests/test_runner_changelog_ui.cjs
node --check apps/web/runner/js/runner.js
```

Expected: PASS.

- [ ] **Step 6: Commit the Runner UI**

```powershell
git add apps/web/runner/index.html apps/web/runner/css/runner.css apps/web/runner/js/runner.js tests/test_runner_ui_structure.py
git commit -m "feat: add runner changelog interface"
```

### Task 9: Integrate online refresh, offline fallback, and complete verification

**Files:**
- Modify: `tests/test_runner_update.py`
- Modify: `tests/test_runner_changelog_api.py`

**Interfaces:**
- Consumes every prior task interface.
- Produces one verified flow: publish body → normalized GitHub release → update selection → pending marker → matching-version startup payload → one acknowledgement, while manual cached history remains usable offline.

- [ ] **Step 1: Add the cross-layer Python integration test**

Create a temporary authored notes file, call `compose_release_notes`, place that body in a fake GitHub release with matching tag/zip asset, run `normalize_releases`, cache it with `refresh_history`, write pending from the selected normalized record, then construct the API payload at the matching bundled version. Assert exact Markdown survives, `shouldAutoShow=True`, acknowledge it, reload payload, and assert `shouldAutoShow=False` while history still contains the release. Patch network to raise and assert `changelog_refresh()` returns the cached history with no exception.

- [ ] **Step 2: Run integration tests and verify RED/GREEN honestly**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_runner_update tests.test_runner_changelog_api -v
```

Expected: PASS after fixing only concrete interface mismatches revealed by the integration test; do not weaken assertions.

- [ ] **Step 3: Run all focused feature tests**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_build_publish tests.test_workflow_hub_build tests.test_runner_update tests.test_runner_changelog_api tests.test_runner_ui_structure tests.test_hub_ui -v
node --test tests/test_hub_grid.cjs tests/test_runner_changelog_ui.cjs
node --check apps/web/hub/js/hub.js
node --check apps/web/runner/js/runner.js
```

Expected: all PASS.

- [ ] **Step 4: Run repository-wide regressions**

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q src apps packaging
Get-ChildItem apps/web -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

Expected: all commands exit 0. If PowerShell is unavailable in the execution shell, run the equivalent Git Bash check without changing scope:

```bash
for file in $(find apps/web -name '*.js' -print); do node --check "$file" || exit 1; done
```

- [ ] **Step 5: Perform a source-mode manual integration smoke test**

Run `.venv\Scripts\python.exe apps\workflow_hub.py`, open a Runner build dialog, and verify: multiline Unicode Markdown is retained; entering first non-whitespace text enables/checks auto-show; manual uncheck survives further non-empty edits; clearing disables/unchecks it. Start a publish dry-run through a test call or build with publishing disabled and inspect the logged command only through the test harness—release text must not appear in process arguments.

Then run `.venv\Scripts\python.exe apps\workflow_runner.py workflows\BrownDust2\workflow.json` and verify the Changelog tab, empty/offline state, responsive mobile navigation, preference persistence, and that a cached test release renders supported Markdown while literal HTML appears as text and unsafe links are not clickable. Remove only the temporary test state created for this smoke test.

- [ ] **Step 6: Commit integration coverage/fixes**

```powershell
git add tests/test_runner_update.py tests/test_runner_changelog_api.py src/runner_update.py apps/workflow_runner.py apps/web/runner/js/runner.js
git commit -m "test: verify runner changelog lifecycle"
```

The implementer must omit unchanged paths from this commit; if Step 1 required tests only, stage only the two test files.
