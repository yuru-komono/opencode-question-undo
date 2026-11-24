# question-undo

> **⚠ Read this before using it on a real session.**
> - This tool makes **destructive changes to a session**. No support is offered.
> - **By default only the session timeline is rewound.** File rollback is an opt-in (default OFF): when enabled, the files touched by the work after the question are also returned to the boundary point.
> - **A staged revert is reversible only until your next send.** Sending while staged commits it, and the hidden tail becomes unrecoverable.
> - **Never use it first on a session involved in production or real work — rehearse on a disposable dummy session until you fully trust the flow.**

A tool to **re-answer a question you answered wrongly** in OpenCode (measured on v2.4.1). It undoes only the work done after the question and has the same question output again. The same three commands are available on all three surfaces (Desktop, Web UI, TUI).

## Why

OpenCode v2.4.1 (released 2026-11-23) still has no undo for question answers. The upstream issue ([anomalyco/opencode#8689](https://github.com/anomalyco/opencode/issues/8689)) was still open as of 2026-11-24, and re-answering questions was explicitly deferred upstream to a separate later issue. This tool only triggers the existing revert (stage/commit) machinery at the question boundary; everything after that (re-running, clearing) uses each surface's standard operations.

The target scenario: after moving past the confirmation step into implementation, you want to redo from that confirmation. Only the later work is discarded; the asking step's text and the question itself survive.

**What this tool does not do:**

- It does not change the question. The re-presented question is identical in text, options and multiple. If the question itself was badly formed, this tool cannot fix it.
- By default it does not roll back files. Unless you enable it, files edited, created or deleted by the work after the question stay as they are (file rollback is an opt-in; the design rationale and how to enable it are in "Safety").

## Requirements

| Requirement | What is required | What happens when it is not met |
|---|---|---|
| OpenCode version | The verified versions are 2.3.2 / 2.4.0 / 2.4.1. A verified version runs silently, **a version newer than the newest verified one, an unverified version inside the verified range, and an unparseable version (suffixes, dev builds, …) warn and run**, **a version older than the oldest verified one is refused** | The three surfaces print a refusal. The CLI runs its read-only modes with a warning, and `--allow-version-drift` runs the rest. The warning goes only to the server log, never to the three surfaces |
| Harness rule | the `question` tool is called in a dedicated step (the rule and the per-path table are below, in this section) | The default boundary is safe; the other paths lose the asking step along with everything in it |
| Git (only when file rollback is enabled) | ① the session's project is a Git repository ② the server process can resolve the `git` CLI ③ snapshots are not disabled in the config | The stage reports that there is nothing to restore, and cancel tells you that file changes made while staged are not returned |
| The `opencode` CLI | the server process can resolve `opencode`; if it cannot, set `QUESTION_UNDO_CLI` to the executable path | stage, apply and cancel cannot run |
| Node.js and Python | Node.js to install the plugin, Python 3 for `tools/smoke.py` | Installation and CLI runs fail |

The `engines: 2.4.1` field in `package.json` records the newest verified version, not an accepted range. After an OpenCode update, re-verify and add the measured version to the verified set.

### Rule: call `question` in a dedicated step

**This tool assumes your harness (system prompt or equivalent) enforces this rule. Without it, the paths in the table below destroy the asking step along with everything in it.**

Rule: the assistant must call the `question` tool in a dedicated step — no body text and no other tool calls in the same step. If explanatory text is needed before a question, end that step first and call `question` in the next one.

| Path | What happens when the question shares a message |
|---|---|
| Default boundary (right after the answered question) | The asking step survives (safe) |
| CLI `--mode question` / the `questionStep` fallback mode | **The whole step goes — body text and tool results included** |
| Right-clicking the asking message and choosing revert | The whole message goes |
| The revert/fork planned upstream in #8689 | The same loss, at message granularity |

With dedicated question steps, message granularity becomes effectively part granularity, and "redo just the answer" is lossless on every path.

**Rule text you can paste into your harness:**

> The assistant must call the `question` tool in a dedicated step: no body text and no other tool calls in the same step. If explanatory text is needed before a question, end that step first and call `question` in the next one. OpenCode's revert is message-granular, so a question sharing a message with other content drags that content into any redo of the question.

## Install

1. `git clone` (or copy) this repository, then run `npm install` in this folder (Node.js required; no build step).
2. Add this folder to the `plugins` array of your global config `~/.config/opencode/opencode.json(c)` (see `config/plugin-snippet.md`).
3. Apply and verify as described in `config/plugin-snippet.md` (restart the server or save the config, then check that the three commands appear in `opencode api get /api/command`).

`/undo-answer` autocompletes in all three surfaces (Desktop window, browser Web UI, TUI).

## Usage (two-stage flow)

**When you notice a wrong answer**: press Esc to stop the running response first (staging is refused while the session runs), then run `/undo-answer` as early as you can.

1. With the session open, type `/undo-answer` in the input box.
   - It locates the latest answered question and stages a `revert` with **the first work message right after the answered question** as the boundary. The later work becomes hidden; the asking step's text and the answered question card survive.
   - The re-presentation instruction is saved in the plugin's server-side storage. The server sends it directly rather than writing it into the composer, so a mistyped edit or a cleared input box cannot lose it.
2. Look at the timeline and decide.
   - **`/undo-answer-apply`** — the server sends the stored instruction. The send commits the stage, and the exact same question is re-presented verbatim.
   - **`/undo-answer-cancel`** — clears the stage and drops the record, restoring the timeline (do this **before any new send**).
3. To only inspect what would be reverted, use the read-only CLI (`--inspect` below).

Do not touch the old answered card. Right-clicking a timeline message and choosing "revert" creates **a new revert at an earlier boundary**; it is not a clear.

### CLI (fallback, measurement, connectivity check)

```
python tools/smoke.py --list                                       # list sessions
python tools/smoke.py --session <sid> --inspect                    # layout after the question and computed boundary (no changes)
python tools/smoke.py --session <sid> --mode work --print-prompt   # print the instruction (no changes)
python tools/smoke.py --session <sid>                              # stage at the default boundary (work mode: only the later work)
python tools/smoke.py --session <sid> --mode question              # stage at the v0.1.0 boundary (questionStep)
python tools/smoke.py --session <sid> --mode work --apply          # send the instruction (/undo-answer-apply equivalent)
python tools/smoke.py --session <sid> --clear                      # clear the stage
python tools/smoke.py --session <sid> --files                      # stage with file rollback enabled (files:true, opt-in)
```

- `--mode work` (default) is the v0.2.0+ behavior: revert from right after the answered question and re-present the same question.
- `--mode question` is the v0.1.0 behavior: revert from the step containing the answered question itself and re-send the previous user message.
- `--apply` does not read the plugin record, so it recomputes the instruction from history (same derivation as `--print-prompt`).
- `--files` enables file rollback (default OFF, opt-in). The three-surface commands are enabled instead by an `undo-files.on` marker in the session's project root, while the CLI reads `undo-files.on` in the current working directory. Mechanism, preconditions and risk are in "Safety".
- Reversible measurement (disposable sessions only, required flag): `python tools/smoke.py --session <sid> --mode work --measure-boundary --disposable`. Stages, verifies the boundary, then auto-clears; nothing is deleted.
- Fully automatic re-run with irreversible deletion happens only with the explicit `--commit --reprompt` flags (deletes from the boundary on, then re-sends the instruction or the previous message). Normally do not use it.
- If the session was already staged by the three-surface commands, staging from the CLI is refused. To continue a CLI-staged state in a surface, use `/undo-answer-apply` (it sends when the boundary matches, even without a record).

## Safety

- **By default only the session timeline is rewound. File rollback (`files:true`) is an opt-in and the default is OFF.** When enabled, the stage uses the per-step start trees upstream keeps in a Git-based shadow repository (`global.data/snapshot/…`; your own git history stays clean) and restores **only the paths touched by the work steps after the boundary**, each to the state at the first post-boundary step that touched it (files created after the boundary are deleted; unrelated paths are untouched). How to enable it: on the three surfaces, an `undo-files.on` marker in the session's project root (existence only; its contents are never read) or the `FILES_MODE` constant in `src/undo-server.js`; on the CLI, `--files` (the CLI also consults `undo-files.on` in the current working directory). Precedence: CLI flag > marker > constant. The preconditions are the Git row of "Requirements" above. Excluded: paths ignored by `.gitignore`, and untracked files over 2 MB. Three reasons the default is OFF: ① it **silently overwrites** edits you made by hand or in another session after the question (upstream #54026); ② on a non-git project upstream reports success while restoring nothing (#38672); ③ the meaning of revert.files may change in the future (#15391). When it is enabled but the project is not a Git repository or the snapshot capture failed, the stage reports that nothing will be restored, and cancel tells you that file changes made while staged are not returned. To roll back files as well without this opt-in, use OpenCode's built-in `/undo` (requires Git).
- Default is **stage only (reversible)**. The commit that deletes history lives only behind explicit CLI flags.
- **The stage is reversible only until the next send.** Sending a new message while staged commits the stage; the hidden tail becomes unrecoverable. Clear with `/undo-answer-cancel` (or `--clear`) before sending.
- Boundaries are per message and **include the boundary message itself**. The default boundary is the work message right after the answered question, so the asking step is never swept up.
- If a revert is already staged at another boundary, or if another surface stages concurrently, the run refuses — it neither overwrites nor clears someone else's stage (and `apply` never sends unless the recorded boundary matches the actual staged one; two-read narrowing, no compare-and-set in 2.3.2).
- Re-presentation records expire after 7 days (prevents replay onto a reused session id). Records of deleted sessions can never be reclaimed because storage exposes no enumeration API (accepted limitation).
- Sessions with an unanswered question on screen are refused: a pending question inside the staged range would remove the question from the timeline entirely, and a later send would make that permanent (measured on v2.3.2).
- Staging fails while the session is running (the command refuses with guidance; the CLI sees HTTP 409 / `SessionBusy`). **Press Esc to interrupt, then run again** — this tool never interrupts automatically.
- The target is only "the latest question answer in this session's chronology". It never searches across fork/subagent history copies.

## Limitations and assumptions

- **Message granularity.** The deletion boundary is per assistant message; every step from the boundary on disappears. If the question tool is called in a dedicated step with no body text (see "Requirements" above), message granularity becomes effectively part granularity.
- **Re-presentation depends on the model.** The instruction carries the question text, options and multiple values verbatim, but the model itself re-runs the call. In measurements on disposable sessions, the re-presented question matched the payload JSON exactly.
- **Missing server-side ctx APIs.** The 2.3.2/2.4.0/2.4.1 server plugin has no `session.revert` or message-list API (re-confirmed on the 2.4.1 SDK), so exactly those three operations (list, stage, clear) go through an `opencode api` bridge (the SWAP-POINT block in `src/undo-server.js`; when upstream exposes the API, replacing just that block is the whole migration).
- **What the version gate was measured to.** The verified set is 2.3.2 / 2.4.0 / 2.4.1. Full three-surface measurements were made on 2.3.2; the 2.4.0 and 2.4.1 re-verifications covered the live server, the CLI boundary computation and command registration (they entered the set before the set rule existed). From now on, a version joins the verified set only after it is measured on all three surfaces. The verdicts and each surface's behavior are in "Requirements" above. When file rollback is enabled and the server is not the last version measured (2.4.1) — including the older members of the verified set — it also warns that how revert.files is stored and restored may change in the future (upstream #15391).
- **Measured on Windows only.** Full-surface measurements were made on Windows 11 with the Desktop/Web/TUI surfaces of OpenCode 2.3.2; the 2.4.0 and 2.4.1 re-verifications covered the live server, the CLI (list/inspect/boundary) and command registration, not a full three-surface rehearsal. The POSIX side (Linux/macOS) is untested; the CLI bridge there resolves `opencode` via `shutil.which` and should work, but nothing is verified.
- **Search window.** The message list is widened to 200 entries; older questions beyond that window are not found, and the tool refuses safely with "no answered question found". Fork/branch-derived sessions rewrite message ids, so ordering is chronological, not lexicographic.
- **No notice line.** A successful stage sends no notice (`session.synthetic` with `resume:false` produces no timeline and no `message.list` entry; measured). With the default resume the model would react to the notice and start talking. Judge success from the staged rendering change and from refusal messages.
- **Boundary fallback.** If an upstream update breaks the "right after the answered question" boundary, changing the single `BOUNDARY_MODE` line in `src/undo-server.js` to `"questionStep"` restores v0.1.0 behavior.

## Troubleshooting

- Commands do not appear: check that the three names are in `opencode api get /api/command`; if not, check the `plugins` config and restart the server.
- "The server process cannot resolve the opencode CLI": the server's PATH lacks `opencode`. Set `QUESTION_UNDO_CLI` to the full executable path.
- "The session is running": press Esc to interrupt, then run `/undo-answer` again.
- "A revert is already staged at another boundary": clear first with `/undo-answer-cancel` (or `--clear`).
- "The staged boundary changed between two reads": another surface staged concurrently. Check the timeline, clear if needed, then re-run.
- "No work message after the answered question": the follow-up work has not started. To redo the question itself, use the CLI's `--mode question`.
- Version mismatch message: the verified versions are 2.3.2 / 2.4.0 / 2.4.1. On a server older than the oldest of them, all three surfaces refuse with a message (to run anyway, use the CLI's `--allow-version-drift`). On an unverified version (newer than the newest one, inside the verified range, or unparseable), it runs with a warning that appears only in the server/sidecar log, never in the UI. After an update, re-check boundary behavior with `smoke.py --list` / `--inspect` before trusting it.

## Removal once upstream implements #8689

When upstream ships revert/fork from user messages with question support, delete the single `plugins` entry and this repository. Nothing else remains in the database or config (server API only). The rule above also improves the granularity of native revert, so it stays worth keeping after removal.

## Provenance and license

Development did not use stock OpenCode. It used the author's personal agent harness based on feature-dev, driving a Qwen-family model (Qwen3.8 Flash Next base, IQ3_S quantized build) running locally on Strata. The loop was repeated for each change: the author conceived the feature idea, the AI examined it and produced options, the author chose, the AI implemented, and an auditor sub-agent AI plus the human double-checked the result. The measurements quoted in this repository are hands-on and human-verified. MIT licensed — see `LICENSE`.

## Maintenance mode

This project is in maintenance mode: no support is offered (issues on this repository are disabled), fixes are opportunistic, and the verified version list stays wherever the last measurement left it. Expect no adaptation to newer OpenCode releases unless someone (possibly you) re-verifies on all three surfaces and adds the version to the list. Forks and improvements are welcome — take the code and make it yours.
