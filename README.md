# question-undo

> **⚠ Read this before using it on a real session.** This tool makes **destructive changes to a session**, and it comes with **no support**. Only the session timeline is rewound: files edited, created or deleted by the work after the question are **not rolled back at all**. A staged revert is **committed by your very next send**, after which the hidden tail is unrecoverable, and the CLI's `--commit` deletes history immediately. **If you notice you answered a question wrongly, stop the running response (Esc) as early as possible and consider running this tool** — the later you notice, the more subsequent work falls inside the revert range. **Never use it first on a session involved in production or real work — rehearse on a disposable dummy session until you fully trust the flow.** Your harness must call the `question` tool in a dedicated step (see "Requirement" below); otherwise the fallback paths destroy the asking step's text and tool results too. This is a personal tool released in good faith: no support, issues are disabled on this repository, and forks and improvements are welcome.

A tool to **re-answer a question you answered wrongly** in OpenCode (measured on v2.4.0). Re-presenting the question is the means: it stages a `revert` right **after** the answered question, so the step that asked the question and the answered question card stay on screen while only the work done afterwards is temporarily hidden, and then the exact same question is re-presented verbatim. Deleting history (commit) is never the default. **It cannot make the assistant rethink a badly formed question** — the re-presented question (text, options, multiple) is identical; if the question itself was wrong, that is out of scope.

On all three surfaces (Desktop, Web UI, TUI) the same three commands are available. Re-presentation is not a draft written into the composer: **the server sends the stored instruction directly**, so a mistyped edit or a cleared input box cannot lose it.

## Why

**The point is re-answering a question you got wrong**; re-presenting the same question verbatim is the means. You undo the answer to a `question` and answer it again. OpenCode v2.4.0 (released 2026-11-23) still has no undo for question answers, and the upstream issue ([anomalyco/opencode#8689](https://github.com/anomalyco/opencode/issues/8689)) was still open as of 2026-11-23 — re-answering questions was explicitly deferred upstream to a separate later issue. This tool only triggers the existing revert (stage/commit) machinery at the question boundary; everything after that (re-running, clearing) uses each surface's standard operations.

**What this tool does not do:**

- It does not change the question. The re-presented question is identical in text, options and multiple. If the question itself was badly formed, this tool cannot fix it.
- It does not roll back files. Files edited, created or deleted by the work after the question stay as they are; only the session timeline is rewound.

The target scenario: after moving past the confirmation step into implementation, you want to redo from that confirmation. Only the later work is discarded; the asking step's text and the question itself survive.

## Install

1. `git clone` (or copy) this repository, then run `npm install` in this folder (Node.js required; no build step).
2. Add this folder to the `plugins` array of your global config `~/.config/opencode/opencode.json(c)` (see `config/plugin-snippet.md`).
3. Apply and verify as described in `config/plugin-snippet.md` (restart the server or save the config, then check that the three commands appear in `opencode api get /api/command`).

`/undo-answer` autocompletes in all three surfaces (Desktop window, browser Web UI, TUI).

## Usage (two-stage flow)

**When you notice a wrong answer**: press Esc to stop the running response first (staging is refused while the session runs), then run `/undo-answer` as early as you can. The later you notice, the more work messages fall inside the revert range, and the stage stays reversible only until your next send.

1. With the session open, type `/undo-answer` in the input box.
   - It locates the latest answered question and stages a `revert` with **the first work message right after the answered question** as the boundary. The later work becomes hidden; the asking step's text and the answered question card survive.
   - The re-presentation instruction is saved in the plugin's server-side storage.
2. Look at the timeline and decide.
   - **`/undo-answer-apply`** — the server sends the stored instruction. The send commits the stage, and the exact same question is re-presented verbatim.
   - **`/undo-answer-cancel`** — clears the stage and drops the record, restoring the timeline. **Valid only before a new send.** Sending anything while staged commits the stage and the hidden tail becomes unrecoverable.
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
```

- `--mode work` (default) is the v0.2.0+ behavior: revert from right after the answered question and re-present the same question.
- `--mode question` is the v0.1.0 behavior: revert from the step containing the answered question itself and re-send the previous user message.
- `--apply` does not read the plugin record, so it recomputes the instruction from history (same derivation as `--print-prompt`).
- Reversible measurement (disposable sessions only, required flag): `python tools/smoke.py --session <sid> --mode work --measure-boundary --disposable`. Stages, verifies the boundary, then auto-clears; nothing is deleted.
- Fully automatic re-run with irreversible deletion happens only with the explicit `--commit --reprompt` flags (deletes from the boundary on, then re-sends the instruction or the previous message). Normally do not use it.
- If the session was already staged by the three-surface commands, staging from the CLI is refused. To continue a CLI-staged state in a surface, use `/undo-answer-apply` (it sends when the boundary matches, even without a record).

## Safety

- **Only the session timeline is rewound.** Files edited, created or deleted by the work after the question are not rolled back at all. `revert/stage` is called with `files:false`; file-snapshot rewind (`files=true`) is verified upstream (it restores only the paths touched by the work steps after the boundary, to their state at the boundary — requires Git), but it is not offered because it also silently overwrites edits you made by hand or in another session after the question. To roll back files as well, use OpenCode's built-in `/undo` (requires Git). This tool makes destructive changes to a session and comes with no support (see the warning at the top).
- Default is **stage only (reversible)**. The commit that deletes history lives only behind explicit CLI flags.
- **The stage is reversible only until the next send.** Sending a new message while staged commits the stage; the hidden tail becomes unrecoverable. Clear with `/undo-answer-cancel` (or `--clear`) before sending.
- Boundaries are per message and **include the boundary message itself**. The default boundary is the work message right after the answered question, so the asking step is never swept up.
- If a revert is already staged at another boundary, the run refuses instead of overwriting it (and `apply` never sends unless the recorded boundary matches the actual staged one).
- If another surface stages concurrently, post-stage verification detects the staged-boundary change across two reads and **refuses without clearing someone else's stage** (2.3.2 has no compare-and-set; this is a narrowing, not an elimination).
- Re-presentation records expire after 7 days (prevents replay onto a reused session id). Records of deleted sessions can never be reclaimed because storage exposes no enumeration API (accepted limitation).
- Sessions with an unanswered question on screen are refused: a pending question inside the staged range would remove the question from the timeline entirely, and a later send would make that permanent (measured on v2.3.2).
- Staging fails while the session is running (the command refuses with guidance; the CLI sees HTTP 409 / `SessionBusy`). **Press Esc to interrupt, then run again** — this tool never interrupts automatically.
- The target is only "the latest question answer in this session's chronology". It never searches across fork/subagent history copies.
- With several surfaces in use at once, a stage made first by another surface makes the recorded boundary mismatch, and the run refuses (mix-up prevention).

## Requirement: call `question` in a dedicated step

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

## Limitations and assumptions

- **Version gate (v0.5.0 policy).** At run time the server version is compared with the verified 2.4.0: **newer versions and unparseable forms (suffixes, dev builds, ...) warn and run; older versions are refused.** The CLI's read-only modes (`--list` / `--inspect` / `--print-prompt`) run with a warning even on older servers, and `--allow-version-drift` is the escape hatch for running on an older one. The plugin-side warning goes only to the server log (the three surfaces have no non-blocking warning channel). The `engines: 2.4.0` field in `package.json` records the verified version, not an accepted range. Re-verify after any OpenCode update.
- **Measured on Windows only.** Full-surface measurements were made on Windows 11 with the Desktop/Web/TUI surfaces of OpenCode 2.3.2; the 2.4.0 re-verification covered the live server, the CLI (list/inspect/boundary) and command registration, not a full three-surface rehearsal. The POSIX side (Linux/macOS) is untested; the CLI bridge there resolves `opencode` via `shutil.which` and should work, but nothing is verified.
- **Message granularity.** The deletion boundary is per assistant message; every step from the boundary on disappears. If the question tool is called in a dedicated step with no body text (required convention, see "Requirement" above), message granularity becomes effectively part granularity.
- **Re-presentation depends on the model.** The instruction carries the question text, options and multiple values verbatim, but the model itself re-runs the call. In measurements on disposable sessions, the re-presented question matched the payload JSON exactly.
- **Missing server-side ctx APIs.** The 2.3.2/2.4.0 server plugin has no `session.revert` or message-list API (re-confirmed on the 2.4.0 SDK), so exactly those three operations (list, stage, clear) go through an `opencode api` bridge (the SWAP-POINT block in `src/undo-server.js`; when upstream exposes the API, replacing just that block is the whole migration). The server process must be able to resolve the `opencode` CLI; if it cannot, set the `QUESTION_UNDO_CLI` environment variable to the executable path (`smoke.py` honors the same variable).
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
- Version mismatch message: this tool is verified on v2.4.0. On an older server all three surfaces refuse with a message (to run anyway, use the CLI's `--allow-version-drift`). On a newer server it runs with a warning that appears only in the server/sidecar log, never in the UI. After an update, re-check boundary behavior with `smoke.py --list` / `--inspect` before trusting it.

## Removal once upstream implements #8689

When upstream ships revert/fork from user messages with question support, delete the single `plugins` entry and this repository. Nothing else remains in the database or config (server API only). The requirement above also improves the granularity of native revert, so it stays worth keeping after removal.

## Provenance and license

Development was carried out in OpenCode (agentic use). The code was generated by a locally running Qwen-family model (Qwen3.8 Flash Next base, IQ3_S quantized build); the design decisions, review and hands-on measurements above are human-verified. MIT licensed — see `LICENSE`.

## Maintenance mode

This project is in maintenance mode: no support is offered (issues on this repository are disabled), fixes are opportunistic, and the version gate stays pinned to whatever OpenCode version was last measured. Expect no adaptation to newer OpenCode releases unless someone (possibly you) re-verifies and bumps the pin. Forks and improvements are welcome — take the code and make it yours.
