# Changelog

Notable changes to this artifact are recorded in this file. The format follows Keep a Changelog 1.1.0 and the versions follow Semantic Versioning.

## [Unreleased]

## [0.6.2] - 2026-11-24

### Changed

- The version shown in the re-presentation instruction is now `[q_undo v0.6.2]`
- README — the top warning is narrowed to four bullets, ordered from the general fact to the specific one
- README — removed statements that were repeated across the introduction, "Why" and the scenario text
- README — added a "Requirements" table that gathers the OpenCode version, the harness rule, Git, CLI resolution and Node.js/Python in one place (English and Japanese)
- README — the version gate is now described as "a version newer than the verified one" and "a version older than the verified one" (English and Japanese)
- README.ja — the whole file now uses polite form

## [0.6.1] - 2026-11-24

### Changed

- The version shown in the re-presentation instruction now tracks the tool's own version (`[q_undo v0.6.1]`)

## [0.6.0] - 2026-11-24

### Added

- Opt-in file rollback (default OFF) — when enabled, the files touched by the work after the question are returned to the boundary point (hand edits or other sessions' changes made after the question are lost)
- CLI `--files` flag and the `undo-files.on` enable marker (consulted by both the three surfaces and the CLI; precedence: CLI flag > marker > constant)
- When staging with file rollback enabled, a "nothing to restore" notice if the project is not a Git repository or the snapshot capture failed
- On cancel with file rollback enabled, a notice that file changes made while staged are not returned
- A warning that the meaning of file rollback may change upstream when it is enabled on an unverified server (#15391)

### Changed

- README — file rollback reworded from "not offered" to "opt-in (default OFF)", with how to enable it and the risk (English and Japanese)

## [0.5.3] - 2026-11-24

### Changed

- OpenCode 2.4.1 measured — the version gate's verified version moves to 2.4.1
- Upstream issue #8689 — confirmed still unimplemented (open as of 2026-11-24)
- README — the top warning is now a bullet list of conclusions, with a pointer to the dedicated-question-step requirement (English and Japanese)
- README — moved the "Requirement" section above "Install" (English and Japanese)
- README — merged duplicated statements across sections (file rollback, stage reversibility, message granularity, concurrent staging)
- README — the purpose/method framing now reads: re-answer the question by undoing the work done after it and having the same question output again
- README — expanded the rationale for why file rollback is not offered (Git-based shadow snapshots, preconditions, exclusions, and the three reasons)
- README — rewrote the provenance section: the author's personal harness based on feature-dev, the Qwen-family model running locally on Strata, and the author/AI double-check loop (English and Japanese)

## [0.5.2] - 2026-11-23

### Changed

- README — clarified why file rollback is not offered: file-snapshot rewind is verified upstream, but it also overwrites edits you or another session made after the question; to roll back files, use OpenCode's built-in `/undo` (requires Git)
- README (Japanese) — unified the writing style
- README (Japanese) — removed English wording that was not a necessary technical term
- README — moved the "Requirement" section to right after "Safety" in both the English and Japanese READMEs
- README — merged the duplicated file-rollback statements into one

## [0.5.1] - 2026-11-23

### Changed

- OpenCode 2.4.0 measured — the version gate's verified version moves to 2.4.0
- Upstream issue #8689 — confirmed still unimplemented (open as of 2026-11-23)
- README — the point of the tool is re-answering a wrongly answered question; re-presenting the question is only the means, and the tool never rethinks the question itself
- README — prominent warnings that the tool is destructive to a session, rewinds only the session timeline (never files) and comes with no support; stop the response as early as possible after noticing a wrong answer
- README — "question in a dedicated step" upgraded from recommendation to requirement, with a per-path loss table and paste-ready harness rule text
- README — the development tool and AI model are now described precisely
- LICENSE — the copyright line now names `yuru-komono`

### Fixed

- CLI session list — no longer crashes when a session title contains characters the console code page cannot encode

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
