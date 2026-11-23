# Changelog

Notable changes to this artifact are recorded in this file. The format follows Keep a Changelog 1.1.0 and the versions follow Semantic Versioning.

## [0.5.0] - 2026-11-23

### Changed

- Runtime version gate — OpenCode versions newer than the verified one warn and run; older versions are refused
- CLI `--allow-version-drift` — now the escape hatch for running on an older server (newer versions run by default)
- Upstream issue #8689 — confirmed still unimplemented (open as of 2026-11-23)

## [0.4.0] - 2026-11-23

### Added

- `/undo-answer` — stages a revert right after the latest answered question; the asking step and the answered question survive (history is not deleted)
- `/undo-answer-apply` — the server sends the stored re-prompt instruction, so the exact same question is re-presented
- `/undo-answer-cancel` — clears the staged revert and restores the timeline (valid only before a new send)
- The three commands work on all three surfaces: Desktop, Web UI and TUI
- CLI `python tools/smoke.py` — session list, stage, clear, inspect, print the instruction, reversible boundary measurement, and (only with explicit flags) delete-and-re-send

Initial public release.
