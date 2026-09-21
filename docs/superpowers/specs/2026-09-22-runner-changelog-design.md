# Runner Changelog Design

## Scope

Add release changelogs to standalone game Runners built and published from Workflow Hub. This does not change the Macro2k suite updater or Designer-only local builds.

## User experience

The Hub Runner build dialog includes an optional Markdown changelog and an "Automatically show after update" switch. The switch turns on when non-empty changelog text is entered and turns off when the text becomes empty; the publisher may override it. Empty changelogs never block build or publish.

After a successful Runner update, the first launch of the new version automatically opens its changelog when all of these conditions hold:

- the running version equals the pending update target;
- the changelog is non-empty;
- the release permits automatic display;
- the Runner user has not disabled automatic changelog display;
- that version has not already been automatically shown.

Closing the dialog records the version as shown. The Runner also exposes a Changelog section that can always be opened manually and lists changelogs for multiple versions, newest first. Disabling automatic display does not hide the manual history.

## Release format and transport

GitHub Releases are the canonical changelog source. Hub writes the Markdown changelog to the release body. A machine-readable HTML comment in the body records the automatic-display flag without affecting GitHub's rendered notes, for example:

```markdown
<!-- macro2k-runner: {"autoShow":true} -->

## Changes

- Added feature X.
```

Only releases whose tag starts with the current Runner's bundled `tagPrefix` are included. Draft releases are excluded. Changelog content is passed from Hub to `packaging/build_runner.py` through a temporary UTF-8 notes file rather than command-line text, preserving multiline Markdown and avoiding shell quoting issues. `gh release create` receives that file through `--notes-file`.

## Runtime data flow

`src/runner_update.py` expands release parsing to return normalized changelog records containing version, tag, Markdown, release page, publication time, and the automatic-display flag. The existing update check continues to return the selected release and its notes.

Before exiting to apply an update, Runner atomically persists the selected release as a pending announcement under a per-Runner location in preserved `data/`. This guarantees that the first launch can show the announcement without network access.

At startup, Runner compares the pending target version with the version in bundled `runner_build.json`. A mismatch means the update did not reach the target, so no announcement is shown. A match makes the announcement available to the frontend. Acknowledging/closing an automatically opened announcement records its version and clears the pending state.

The Runner refreshes changelog history from GitHub when online and atomically caches the normalized records under `data/`. Network or parsing failures retain and use the last valid cache. A fresh installation can therefore fetch older matching releases, while an offline installation displays whatever has already been cached.

## Runner interface

The Runner gains:

- a Changelog navigation/section entry;
- a version list and selected release content, newest first;
- a post-update changelog dialog;
- a setting named "Automatically show changelog after updates", enabled by default;
- optional links to the matching GitHub Release.

Markdown is rendered as a restricted safe subset: headings, paragraphs, ordered and unordered lists, emphasis, code, fenced code blocks, block quotes, and HTTPS links. Raw HTML is displayed as text or discarded. Content is constructed through DOM nodes/text content, never assigned untrusted release text through `innerHTML`. Links accept only HTTPS GitHub/web targets and open through the project's safe external-link path.

## Build integration

`apps/web/hub/js/hub.js` adds changelog authoring and auto-show controls to the existing build dialog and sends both values through the Hub API.

`apps/workflow_hub.py` validates the values, owns the temporary notes file for the lifetime of the build subprocess, and passes the file plus auto-show choice to the packaging command.

`packaging/build_runner.py` reads the notes, adds the metadata comment, and publishes with `gh release create --notes-file`. The existing hard-coded release sentence is used only when no changelog was supplied, with automatic display disabled.

The existing version persistence defect is fixed in the same flow: save the successfully built version against the resolved workflow file rather than an empty `--flow-path` value.

## State and failure handling

All changelog state lives in `data/`, which the update script preserves. JSON writes use a temporary sibling followed by atomic replacement. Corrupt state or cache files are ignored without preventing Runner startup.

The pending marker is written only after the target release and package have been validated and immediately before update handoff. It is not sufficient by itself to display the dialog; the running bundled version must match the target. Failed copy/relaunch therefore cannot display a changelog for a version that is not running.

An empty changelog, malformed metadata comment, unavailable network, or GitHub API error never blocks build execution, Runner startup, update checks, or manual use of cached history. Unknown metadata defaults to automatic display disabled.

## Testing

Tests cover:

- Hub/build argument transport and temporary notes-file lifetime;
- GitHub publish command using `--notes-file` and encoded auto-show metadata;
- fixed workflow version persistence using the resolved workflow path;
- release filtering by per-game tag prefix and normalized changelog history;
- metadata parsing defaults and malformed metadata;
- atomic pending/cache state and corrupt-file fallback;
- show-once behavior only when current and target versions match;
- user-level automatic-display preference;
- safe Markdown rendering, including blocked raw HTML and unsafe link schemes;
- offline history from cache and network-refresh behavior.

Existing build, Runner UI structure, update, Python, and JavaScript test suites must remain green.
