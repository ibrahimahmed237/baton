# Baton app

SwiftUI menu-bar app and window for Baton. It shows what the engine returns and
sends the user's choices back; it holds no sync rules and builds no sentences.
Swift 6 toolchain, no external packages (the tests use the bundled Swift Testing
framework).

## Build and test

```
app/scripts/check.sh                 # swift build, then swift test
app/scripts/check.sh --filter Name   # extra arguments go to swift test
```

The script is the one command to run before handing work back. It exits non-zero
when the build or any test fails.

Why the script picks an SDK: on a Mac whose Command Line Tools were updated, the
plain `swift build` can pick an SDK whose SwiftUI macros (`@State`, `@Environment`)
have no matching compiler plugin ("external macro implementation type ... could
not be found"), and `swift test` cannot find the testing macros. `check.sh` first
tries the plain toolchain with a quick SwiftUI compile. If it fails, it tries the SDKs under
`/Library/Developer/CommandLineTools/SDKs`, newest first, uses the first one that
compiles SwiftUI (`SDKROOT`). It adds the testing plugin directory
`.../usr/lib/swift/host/plugins/testing` to `swift test` when it exists, including
when `SDKROOT` was explicitly supplied. The
newest SDK is not always the one that works; the probe, not the version number,
decides. Set `SDKROOT` yourself to skip the search.

Module caches default to `.build/check-cache/` so the same command works in a
managed environment that cannot write the user's global cache. Explicit
`CLANG_MODULE_CACHE_PATH` and `SWIFT_MODULECACHE_PATH` overrides are respected.
The build and tests use SwiftPM's `--disable-sandbox` for manifest execution;
SwiftPM's nested manifest sandbox cannot start inside the managed command
sandbox on this Mac. This does not change Baton's app permissions.

Run the app with fixtures: `swift run Baton` (same SDK note; for example
`SDKROOT=<sdk> swift run Baton`). It launches the fixture-backed menu-bar extra
and links window. The app uses the bundled `Fixtures` directory; another client
can be injected into `AppState`. Rendered PNGs of every screen state are written
to `Snapshots/` (git-ignored) by the tests.

`BatonKit` contains contract models and two `EngineClient` implementations.
`FixtureEngine(directory:state:states:)` chooses a default state (`sample`) and
optional per-command overrides. Arguments never select a state, but they can pick a variant of it: `--link N`, `--to TOOL[:ID]` with `--mode`, and `--replace TOOL` look for `<command>.<state>_<variant>.json` first.
`ProcessEngine()` runs `/usr/bin/env baton`; for an explicit executable, pass
its URL and `prefixArguments: []`. Arguments go directly to `Process`, never a
shell. Mutating commands default to previews; `.confirm(planID)` replaces the
preview flag. The fixture JSON contains invented conversations only.

## Contract assumptions to resolve

- Command cells use shorthand without scalar types. Link, turn and event IDs
  are integers; local chat IDs and plan IDs are strings. Counts and tokens are
  integers; percentages, elapsed seconds and numeric settings are doubles.
  Timestamps remain ISO 8601 strings, avoiding an unspecified fractional-second
  policy. Tool names and state/action/mode/tone values remain strings for growth.
- `Note.values` can contain arbitrary JSON, including nested arrays and objects.
  `NoteButton.primary` is optional because the example omits it; omitted means
  no primary designation. `status_line` is optional because not every note is a
  status line, though its nullability is not specified.
- `Turn.messages` is optional because it is only returned with `--messages`.
  `TurnMessage.tool` is optional for prompts and replies. `ended_at` is optional
  for an unfinished turn, though that null case is not documented.
- `Usage.size` and `percent` are nullable when context size is unknown, as
  referenced by D7. A non-null `limit` may have a null `resets_at`. `waiting_reason`
  is nullable when nothing waits. `next_message` remains required.
- `Side.chat` remains required even when `condition.exists` is false; missing
  chats retain their last known reference. The contract does not define how a
  missing side's chat is represented.
- `Plan.link_id` is nullable/omittable for an unlinked copy or preview that has
  not created a link. `MergeShowResult.last_shared` and `UndoResult.ends_at` are
  nullable when there is no shared or remaining turn. These cases need explicit
  contract definitions.
- Setup `version` is nullable for an uninstalled tool. `facts` has no JSON schema
  in CONTRACT.md; it is preserved as a JSON dictionary. The sample uses the
  field names from ARCHITECTURE.md, uppercase visibility/write-window strings,
  boolean `context_size_known`, and a string array `checked_versions`. Those
  encodings need confirmation. Merge `presets` likewise remains arbitrary JSON;
  the sample assumes objects with `id` and `order`.
- History event `tool` is nullable for a link-wide event. Settings responses
  contain all ten listed settings; unknown keys are ignored, and missing known
  keys fail decoding. Whether `settings set` returns a full snapshot or a patch
  is unspecified.
- Errors are assumed to be `{"error":{"kind":...,"note":Note}}`. Both fields
  are optional because the envelope is not actually defined. A note, when
  supplied, is preserved for views; a nonzero exit without an envelope preserves
  its exit status and stderr. Structured errors take precedence over exit status,
  including expected refusals exiting zero. Null/non-object error payloads fail
  decoding rather than producing a fabricated note.
- `catch-up` explicitly returns tool-specific non-JSON output, contradicting the
  general JSON rule. It runs without `--json` and preserves stdout verbatim in
  `CatchUpResult.output`. Its fixture is a local `{"output":...}` wrapper, not a
  claimed CLI response. The raw tool-specific format remains undefined.
- Subcommands use hyphenated fixture keys: `setup-install`, `merge-show`,
  `ask-add`, `settings-get`, `settings-set`; regular commands retain their names.
  Shared-object fixtures use kebab-case names. The contract defines no filename
  convention for subcommands or standalone objects and no default state.
- Slash-grouped commands each have a separate method and result type. Plan
  results have flattened fields, including extensions for continue, undo, brief
  and relaunch. No CLI argument spelling is given for lists: `--order` and
  `--tools` use comma-separated values; `--answer` is passed as the supplied
  string because it is unclear whether A means answer text or an answer ID.
- The universal dry-run/confirm rule conflicts with non-plan mutation results
  (install, pause/resume, turn marks, settings set), which supply no plan ID.
  These methods expose preview/confirm anyway, following the rule; the engine
  must define where their confirmation IDs come from. `ask`, `open`, `notify`
  and `catch-up` are treated as immediate query/app-control/hook calls with no
  preview flag, following their command rows. Whether those actions also need
  confirmation is unspecified.

D0 follows the requested Swift Package layout instead of the planned Xcode
layout, and hand-makes fixtures instead of waiting for engine contract tests.
Future packages can replace them with generated responses. D1 styling, D12
refresh scheduling and D13 transport-error presentation are intentionally
outside this package.
