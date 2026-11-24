// undo-server.js — server-side plugin part that redoes only the latest answered question
// (OpenCode 2.4.1 measured, stage-only by default).
//
// Flow: /undo-answer → locate the latest answered question → compute the boundary →
//       revert/stage (files:false) + save a record →
//       /undo-answer-apply sends the stored instruction via session.prompt (sending commits the
//       stage and re-presents the question) →
//       /undo-answer-cancel clears the stage and drops the record (only before a new send).
// There is no confirm dialog: the two-stage flow (stage → eyeball the timeline → apply/cancel)
// is shared by all three surfaces (Desktop, Web UI, TUI).
// commit (irreversible deletion) is never done here; only via the explicit CLI flag in tools/smoke.py.
// Removal: delete this file + src/undo-kernel.js and the single plugins entry in the config.
//
// The server-side ctx has no `session.revert.*` and no message list (measured on the 2.3.2 SDK:
// the Pick list in dist/promise/session.d.ts and the allowlist in adapter.js; re-confirmed still
// missing on the 2.4.0/2.4.1 SDKs, v0.5.1/v0.5.3). Only those three
// operations go through the SWAP-POINT block below calling `opencode api`. When upstream exposes
// ctx.session.revert, replacing just that block is the whole migration.
//
// BOUNDARY_MODE:
//   afterQuestionStep = v0.2.0 default. The boundary is the first work message right after the
//                       answered question: the asking step's summary text and the answered
//                       question survive; only the later work is reverted.
//   questionStep      = v0.1.0 behavior. The boundary is the message containing the question,
//                       and the previous user message is re-sent.

import { Plugin } from "@opencode/plugin";
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import {
  MAX_INSTRUCTION_CHARS,
  PayloadTooLarge,
  VERIFIED_VERSIONS,
  buildInstruction,
  compareMessages,
  compareVersions,
  computeWorkBoundary,
  extractPayload,
  gateVerdict,
  resolveFilesMode,
  tailOutcome,
} from "./undo-kernel.js";

// The verified version set lives in src/undo-kernel.js (VERIFIED_VERSIONS, v0.7.0 onward).
// PINNED_VERSION is its newest entry: it names the measured version in warnings and in the
// package.json engines field, and is not the accepted range (see README).
// Gate policy (v0.7.0): a member of the verified set runs silently; a version newer than the
// newest entry, an unlisted version between the oldest and the newest, and an unparseable
// version warn and run; a version older than the oldest entry is refused.
const PINNED_VERSION = "2.4.1";

// Boundary mode. afterQuestionStep is measured on v2.3.2 and re-verified on v2.4.0 and v2.4.1 (v0.5.1, v0.5.3).
// If an upstream update breaks the
// after-boundary, flip this one line to questionStep (v0.1.0 behavior).
const BOUNDARY_MODE = "afterQuestionStep";

// Unknown values (typos) must not silently fall back to the v0.2.0 boundary, so only these two are allowed.
const KNOWN_BOUNDARY_MODES = ["afterQuestionStep", "questionStep"];

// Effective mode for file rollback (files:true). Default false = files are not rolled back
// (the safe default for all three surfaces: Desktop, Web UI, TUI). The effective value is
// resolveFilesMode(CLI flag, marker existence, this constant); the three surfaces have no CLI
// flag, so that input is false. A FILES_MARKER file in the project root enables it by existence
// alone and its contents are never read. Hand-mirrored with FILES_MODE in tools/smoke.py.
const FILES_MODE = false;
const FILES_MARKER = "undo-files.on";

// Record key namespace (no collision with other plugins).
const RECORD_PREFIX = "question-undo/record/";

// Record TTL. Guards against an old record being replayed onto a reused session id: on read,
// an expired record is dropped and treated as missing. Records of deleted sessions can never be
// reclaimed because storage exposes no enumeration API (accepted limitation; documented in README).
const RECORD_TTL_MS = 7 * 24 * 60 * 60 * 1000;

// Session id shape (same discipline as tools/smoke.py; always checked before URL interpolation).
const SID_RE = /^[A-Za-z0-9_-]+$/;

// Message id shape (checked before it reaches stage arguments; includes fork-style `<base>_<counter>`).
const MID_RE = /^[A-Za-z0-9_.-]+$/;

// message.list default page is the newest 50 (measured on v2.3.2). limit=1000 returns HTTP 400, so use 200.
const MSG_LIMIT = 200;

// Bridge time limit. Exceeding it is a refusal, not an execution interrupt.
const BRIDGE_TIMEOUT_MS = 30_000;

// Environment variable overriding the resolved `opencode` CLI (e.g. to point at a bundled exe).
const CLI_ENV = "QUESTION_UNDO_CLI";

// Characters rejected when the bridge would go through cmd.exe. Bridge arguments are only
// validated ids and fixed JSON, so these should never appear; refuse before any quoting debate.
const CMD_META = /[()%!^&|<>]/;

const TEXT = {
  description: "revert/stage from right after the latest answered question (history is not deleted)",
  applyDescription: "send the stored re-prompt instruction for the staged revert (sending commits the stage)",
  cancelDescription: "clear the staged revert and drop the record (only valid before a new send)",
  versionMismatch: (found) =>
    `The server version is ${found}, older than the oldest verified version (${VERIFIED_VERSIONS.join(" / ")}). Refusing to run. ` +
    "To run on an older server anyway, use tools/smoke.py with --allow-version-drift (CLI only, at your own risk).",
  versionDrift: (found, verdict) =>
    `question-undo: the server version is ${found} (verified: ${VERIFIED_VERSIONS.join(" / ")}; verdict ${verdict}). ` +
    "Continuing with a warning only: behavior is guaranteed only on the verified versions.",
  filesSemantics: (found) =>
    `question-undo: file rollback (files:true) is measured on the verified ${PINNED_VERSION}. Server ${found} is unverified, and how revert.files is stored and restored may change in the future (upstream #15391).`,
  cliMissing: "The server process cannot resolve the opencode CLI. Check PATH or set the QUESTION_UNDO_CLI environment variable.",
  badSessionID: "Malformed session ID. Aborting.",
  listFailed: (msg) => `Failed to list messages: ${msg}`,
  noQuestion: "No completed question answer was found in this session.",
  pending: "An unanswered question is displayed. Staging in this state would remove the question from the timeline entirely, and a later send would make that permanent (unrecoverable). Answer or cancel the question first.",
  existingStage: "A revert is already staged at another boundary. Run /undo-answer-cancel (or smoke.py --clear) first.",
  sessionGetFailed: "Failed to read session info. Aborting because we cannot confirm whether another boundary is staged (to prevent replacing a stage).",
  noWork: "There is no work message after the answered question, so there is nothing to revert. To redo the question itself, use tools/smoke.py --mode question.",
  adminOnly: "After the answered question there are only admin messages (idle, system, ...), no work message (use tools/smoke.py --mode question).",
  payloadTooLarge: (msg) => `The question is too large to build the instruction (${msg}). Nothing was staged.`,
  emptyReprompt: "The message to re-send (the previous user message) is empty. Aborting.",
  busy: "The session is running, so staging failed. Press Esc to interrupt, then run /undo-answer again (this tool never interrupts automatically).",
  stageFailed: (msg) => `revert/stage failed: ${msg}`,
  stageFailedButCleared: (msg) =>
    `revert/stage reported an error, but a stage had taken effect so it was cleared (${msg}). ` +
    "Check that the timeline was restored.",
  recordWriteFailed: (msg) =>
    `Staged, but the re-presentation record could not be saved (${msg}). ` +
    "Cancel with /undo-answer-cancel. Even without a record, /undo-answer-apply can send if the staged boundary matches.",
  cliPathUnsafe: "The resolved opencode CLI path contains shell metacharacters; refusing to run the bridge.",
  stageVerifyFailedCleared: "Could not confirm the stage. A clear was attempted. Check that the timeline was restored.",
  stageRace: "The staged boundary changed between two reads (another surface may have staged concurrently). Aborting without clearing someone else's stage. Check the timeline and run /undo-answer-cancel if needed.",
  stageDone: (boundary, filesEnabled) =>
    `question redo: staged (boundary ${boundary}). The later work is hidden. ` +
    (filesEnabled
      ? "File rollback: ON (files the work after the boundary touched are returned to the boundary point; hand edits or other sessions' changes made after the question are lost). "
      : "File rollback: OFF (files are unchanged; enable it with tools/smoke.py --files or an undo-files.on file in the project root). ") +
    `/undo-answer-apply re-presents the same question; /undo-answer-cancel clears (valid only before a new send).`,
  stageNoFiles: "File rollback is ON but there is nothing to restore (not a Git repository, or the snapshot capture failed). Files are unchanged.",
  foreignStage: "A staged revert exists at a different boundary (it does not match the recorded one). Aborting without replacing it. Run /undo-answer-cancel first.",
  recordGone: "No re-presentation record was found and the same boundary cannot be re-derived from history. Run /undo-answer again.",
  noStagedApply: "This session has neither a staged revert nor a re-presentation record. Run /undo-answer first.",
  clearedNotCommitted: "The stage appears to have been cleared (the boundary message is still in history). The re-prompt will not be sent. To redo, run /undo-answer.",
  applied: "Sent the question re-prompt instruction (the send committed the stage).",
  cancelled: "Cleared the staged revert and dropped the record. The timeline is restored.",
  cancelledFilesWarn: "Cleared the staged revert and dropped the record. File rollback was ON but no snapshot existed, so file changes made while staged are not returned (only the timeline is restored).",
  noStaged: "This session has no staged revert (the record was dropped too).",
  clearFailed: (msg) => `Failed to clear the revert: ${msg}`,
  applyPromptFailed: (msg) =>
    `Failed to send the instruction: ${msg}. The stage is still in place. ` +
    "Run /undo-answer-apply again, or fetch the text with tools/smoke.py --mode work --print-prompt and send it manually.",
};

// ---------------------------------------------------------------------------
// SWAP-POINT: bridge for only the 3 operations missing from the 2.3.2/2.4.0/2.4.1 server ctx.
// When upstream exposes ctx.session.revert / message.list, replace just this block.
// Direct HTTP is UnauthorizedError (measured), so going through `opencode api` is required
// (same approach as tools/fetch_api.py).
// ---------------------------------------------------------------------------

// Resolve `opencode` from PATH + PATHEXT. Preferring .exe is desirable but the Windows
// resolution order (directory order → PATHEXT order) is followed. On Desktop the resolved
// target is a .cmd shim (measured).
function resolveCli() {
  const override = process.env[CLI_ENV];
  if (override) return override;
  const dirs = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
  const exts =
    process.platform === "win32"
      ? (process.env.PATHEXT || ".EXE;.CMD;.BAT;.COM").split(";").filter(Boolean)
      : [""];
  for (const dir of dirs) {
    for (const ext of exts) {
      const candidate = path.join(dir, "opencode" + ext.toLowerCase());
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
}

// Quote one argument using MSVC argv parsing rules (needed because we build the string ourselves
// when going through cmd.exe).
function winQuote(arg) {
  if (arg !== "" && !/[\s"^\\]/.test(arg)) return arg;
  let out = "";
  let slashes = 0;
  for (const ch of arg) {
    if (ch === "\\") {
      slashes += 1;
      continue;
    }
    if (ch === '"') {
      out += "\\".repeat(slashes * 2 + 1) + '"';
      slashes = 0;
      continue;
    }
    out += "\\".repeat(slashes) + ch;
    slashes = 0;
  }
  out += "\\".repeat(slashes * 2);
  return `"${out}"`;
}

// Run `opencode api <METHOD> <path> [--data <json>]` as an argv array (never a shell string).
function runCli(cli, args, cwd) {
  return new Promise((resolve, reject) => {
    const useShim = process.platform === "win32" && /\.(cmd|bat)$/i.test(cli);
    let child;
    if (useShim) {
      // Node's spawn cannot execute .cmd/.bat directly (measured: EINVAL). Pass one
      // self-quoted string to cmd.exe /c (/d /s disables automatic quote fixup).
      const line = [cli, ...args].map(winQuote).join(" ");
      child = spawn("cmd.exe", ["/d", "/s", "/c", `"${line}"`], {
        cwd,
        windowsVerbatimArguments: true,
        windowsHide: true,
        shell: false,
      });
    } else {
      child = spawn(cli, args, { cwd, shell: false, windowsHide: true });
    }
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`opencode CLI stopped responding after ${BRIDGE_TIMEOUT_MS / 1000}s`));
    }, BRIDGE_TIMEOUT_MS);
    child.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
  });
}

// Return the `data` field on success (or the whole body if absent). Failures are Errors
// (carrying SessionBusy / 409 as text).
async function apiCall(location, method, apiPath, data) {
  const cli = resolveCli();
  if (!cli) throw new Error(TEXT.cliMissing);
  // The resolved CLI path itself is also checked for cmd metacharacters (it comes from PATH or
  // QUESTION_UNDO_CLI, so refuse outright instead of relying on winQuote's quoting conditions).
  if (CMD_META.test(cli)) throw new Error(TEXT.cliPathUnsafe);
  const args = ["api", method, apiPath];
  if (data !== undefined && data !== null) args.push("--data", JSON.stringify(data));
  for (const arg of args) {
    if (CMD_META.test(arg)) throw new Error(`bridge refused: argument contains cmd metacharacters (${apiPath})`);
  }
  const r = await runCli(cli, args, location);
  const raw = (r.stdout || "").trim();
  let body = null;
  try {
    body = JSON.parse(raw);
  } catch (e) {
    body = null;
  }
  if (r.code !== 0) {
    const detail = ((r.stderr || "") + " " + (raw || "")).trim().slice(0, 400);
    throw new Error(`${method} ${apiPath} -> exit ${r.code}: ${detail || "unknown error"}`);
  }
  if (body && typeof body === "object" && "data" in body) return body.data;
  return body;
}

async function listMessages(location, sessionID) {
  const d = await apiCall(location, "GET", `/api/session/${sessionID}/message?limit=${MSG_LIMIT}`);
  return (d && d.data) || d || [];
}

async function stageRevert(location, sessionID, messageID, files) {
  await apiCall(location, "POST", `/api/session/${sessionID}/revert/stage`, { messageID, files });
}

async function clearRevert(location, sessionID) {
  await apiCall(location, "DELETE", `/api/session/${sessionID}/revert`);
}
// ---------------------------------------------------------------------------
// end SWAP-POINT
// ---------------------------------------------------------------------------

const recordKey = (sessionID) => `${RECORD_PREFIX}${sessionID}`;
const readRecord = async (ctx, sessionID) => {
  const rec = (await ctx.storage.get(recordKey(sessionID))) || null;
  if (!rec) return null;
  // Expired records are dropped and treated as missing (the apply side then refuses safely via its
  // recompute-and-match path when the record is absent).
  if (typeof rec.createdAt === "number" && Date.now() - rec.createdAt > RECORD_TTL_MS) {
    await dropRecord(ctx, sessionID).catch(() => null);
    return null;
  }
  return rec;
};
const writeRecord = (ctx, sessionID, record) => ctx.storage.set(recordKey(sessionID), record);
const dropRecord = (ctx, sessionID) => ctx.storage.remove(recordKey(sessionID));

// Collect assistant messages holding a completed question tool part and return the latest one
// chronologically. Never trust the list order: id lexicographic order breaks in fork sessions,
// so compareMessages is used.
function findLatestQuestion(messages) {
  let best = null;
  for (const m of messages || []) {
    if (!m || m.type !== "assistant") continue;
    const parts = (m.content || []).filter(
      (p) => p && p.type === "tool" && p.name === "question" && p.state && p.state.status === "completed",
    );
    if (parts.length === 0) continue;
    if (!best || compareMessages(m, best.message) > 0) {
      best = { message: m, parts };
    }
  }
  return best;
}

// Boundary per BOUNDARY_MODE ({ ok, message, rule } | { ok:false, reason }).
function computeBoundary(messages, questionMessage) {
  if (!KNOWN_BOUNDARY_MODES.includes(BOUNDARY_MODE)) {
    return { ok: false, reason: `unknown BOUNDARY_MODE (${BOUNDARY_MODE})` };
  }
  if (BOUNDARY_MODE === "questionStep") {
    return { ok: true, message: questionMessage, rule: "questionStep" };
  }
  return computeWorkBoundary(messages, questionMessage);
}

// Whether any pending (unanswered) question part exists. If it falls inside the staged range the
// question disappears entirely and a later new send makes that permanent (deletion), so refuse.
function hasPendingQuestion(messages) {
  return (messages || []).some(
    (m) =>
      m && m.type === "assistant" &&
      (m.content || []).some((p) => p && p.type === "tool" && p.name === "question" && (!p.state || p.state.status !== "completed")),
  );
}

// The user message text right before the boundary (the text re-sent in questionStep mode).
function lastUserTextBefore(messages, boundaryMessage) {
  let best = null;
  for (const m of messages || []) {
    if (!m || m.type !== "user") continue;
    if (!(compareMessages(m, boundaryMessage) < 0)) continue;
    if (!best || compareMessages(m, best) > 0) best = m;
  }
  if (!best) return "";
  if (typeof best.text === "string" && best.text.trim() !== "") return best.text.trim();
  return (best.content || [])
    .filter((p) => p && p.type === "text")
    .map((p) => p.text || "")
    .join("\n")
    .trim();
}

// The version string is externally supplied (SDK / API) and reaches the server log and the
// 500 message. To keep newlines or ANSI from forging log lines, display it only when it is
// printable ASCII ≤32 chars; anything else displays as "unknown" (the verdict itself is
// handled as unknown by gateVerdict). Mirror: the display_version regex in tools/smoke.py
// — a hand-mirrored pair; update both sides together.
const DISPLAY_VERSION_RE = /^[\x20-\x7e]{1,32}$/;
const displayVersion = (v) => (typeof v === "string" && DISPLAY_VERSION_RE.test(v) ? v : "unknown");

// Version gate (v0.7.0): only "older" (older than the oldest verified version) throws, surfaced
// as HTTP 500 on all three surfaces. "newer" / "unverified" / "unknown" warn via console.error and
// continue (the server ctx has no non-blocking user-facing channel; see README limitations).
// "unverified" is a version at or above the oldest entry and at or below the newest one that is
// not itself listed. The warning is evaluated per execution, never cached.
function gate(ctx, filesEnabled = false) {
  const verdict = gateVerdict(ctx.app.version, VERIFIED_VERSIONS);
  if (verdict === "older") throw new Error(TEXT.versionMismatch(displayVersion(ctx.app.version)));
  if (verdict !== "same") {
    console.error(TEXT.versionDrift(displayVersion(ctx.app.version), verdict));
  }
  // The restore semantics of files:true are measured on PINNED_VERSION (the newest verified
  // version, i.e. the last one measured). On any other server, including older members of the
  // verified set, how revert.files is stored and restored may change (upstream #15391). This is
  // deliberately not keyed to set membership: with v0.7.0 making 2.3.2 and 2.4.0 "same", keying
  // it there would silence the notice for exactly those versions. Warn only on the stage path
  // (undoAnswer) and only when files is enabled.
  if (filesEnabled && compareVersions(ctx.app.version, PINNED_VERSION) !== "same") {
    console.error(TEXT.filesSemantics(displayVersion(ctx.app.version)));
  }
}

function checkSessionID(sessionID) {
  if (!sessionID || !SID_RE.test(sessionID)) throw new Error(TEXT.badSessionID);
}

// Notice line. With `resume:false` it appears in neither the timeline nor message.list (it enters
// the inbox awaiting the next wake; measured on v0.3.0, re-confirmed on v0.4.0). The ADMIN_TYPES
// protection in boundary computation is still needed because synthetic messages injected via
// other paths such as fork DO appear in the list. With the default resume, the model reacts to
// the notice line and creates a turn (measured: with false, zero new assistant turns).
async function say(ctx, sessionID, text) {
  await ctx.session.synthetic({ sessionID, text, description: "question-undo", resume: false }).catch(() => null);
}

// /undo-answer — compute boundary → stage → save record.
async function undoAnswer(ctx, sessionID) {
  const filesEnabled = resolveFilesMode(false, existsSync(path.join(ctx.location.directory, FILES_MARKER)), FILES_MODE);
  gate(ctx, filesEnabled);
  checkSessionID(sessionID);

  let messages;
  try {
    messages = await listMessages(ctx.location.directory, sessionID);
  } catch (e) {
    throw new Error(TEXT.listFailed(e.message));
  }
  if (hasPendingQuestion(messages)) throw new Error(TEXT.pending);
  const found = findLatestQuestion(messages);
  if (!found) throw new Error(TEXT.noQuestion);

  const pre = await ctx.session.get({ sessionID }).catch(() => null);
  if (!pre) throw new Error(TEXT.sessionGetFailed);
  if (pre.revert) throw new Error(TEXT.existingStage);

  const boundary = computeBoundary(messages, found.message);
  if (!boundary.ok) {
    throw new Error(boundary.reason === "admin-only" ? TEXT.adminOnly : TEXT.noWork);
  }

  // Build the instruction BEFORE staging (independent of how the post-stage list returns hidden items).
  let instruction;
  if (BOUNDARY_MODE === "questionStep") {
    instruction = lastUserTextBefore(messages, boundary.message);
    if (!instruction) throw new Error(TEXT.emptyReprompt);
  } else {
    try {
      instruction = buildInstruction(extractPayload(found.parts));
    } catch (e) {
      if (e instanceof PayloadTooLarge) throw new Error(TEXT.payloadTooLarge(e.message));
      throw e;
    }
  }

  if (!MID_RE.test(boundary.message.id)) {
    throw new Error(`bridge refused: malformed boundary message id (${boundary.message.id})`);
  }
  try {
    await stageRevert(ctx.location.directory, sessionID, boundary.message.id, filesEnabled);
  } catch (e) {
    const text = e && e.message ? e.message : String(e);
    // Even when the bridge call fails, a stage may have taken effect server-side (a timeout that
    // kills only the cmd.exe wrapper can let the grandchild CLI finish staging later). A ghost
    // stage would be committed by the user's next send and the hidden tail would vanish
    // unrecoverably. On failure paths too, check reality and clear before reporting if staged
    // (same posture as the verify-failure path).
    const now = await ctx.session.get({ sessionID }).catch(() => null);
    if (now && now.revert) {
      await clearRevert(ctx.location.directory, sessionID).catch(() => null);
      throw new Error(TEXT.stageFailedButCleared(text));
    }
    throw new Error(text.includes("SessionBusy") || text.includes("409") ? TEXT.busy : TEXT.stageFailed(text));
  }

  const after = await ctx.session.get({ sessionID }).catch(() => null);
  if (!after || !after.revert || after.revert.messageID !== boundary.message.id) {
    // Race narrowing: 2.3.2 has no compare-and-set on revert. Read once more; if the staged id
    // changed between the two reads, another surface staged concurrently, so refuse instead of
    // clearing someone else's stage.
    const recheck = await ctx.session.get({ sessionID }).catch(() => null);
    const firstId = after && after.revert ? after.revert.messageID : null;
    const secondId = recheck && recheck.revert ? recheck.revert.messageID : null;
    if (firstId !== secondId) throw new Error(TEXT.stageRace);
    // Do not leave it armed while reporting failure: attempt a clear before notifying.
    await clearRevert(ctx.location.directory, sessionID).catch(() => null);
    throw new Error(TEXT.stageVerifyFailedCleared);
  }

  try {
    await writeRecord(ctx, sessionID, {
      v: 1,
      sessionID,
      questionMessageID: found.message.id,
      boundaryMessageID: boundary.message.id,
      boundaryRule: boundary.rule,
      mode: BOUNDARY_MODE,
      files: filesEnabled,
      instruction,
      createdAt: Date.now(),
    });
  } catch (e) {
    // The stage succeeded. Do not surface the record-save failure as a raw error; add recovery steps.
    throw new Error(TEXT.recordWriteFailed(e && e.message ? e.message : String(e)));
  }

  const outcome = tailOutcome(messages, found.message);
  const tail = { succeeded: "completed", failed: "failed", interrupted: "interrupted" }[outcome] || "running or no end marker";
  const noFiles = filesEnabled && (!Array.isArray(after.revert.files) || after.revert.files.length === 0);
  const filesNote = noFiles ? ` ${TEXT.stageNoFiles}` : "";
  await say(ctx, sessionID, `${TEXT.stageDone(boundary.message.id, filesEnabled)}${filesNote} rule ${boundary.rule} · tail run state: ${tail}`);
}

// /undo-answer-apply — send the stored instruction (the send commits the stage).
async function undoApply(ctx, sessionID) {
  gate(ctx);
  checkSessionID(sessionID);

  let messages;
  try {
    messages = await listMessages(ctx.location.directory, sessionID);
  } catch (e) {
    throw new Error(TEXT.listFailed(e.message));
  }
  if (hasPendingQuestion(messages)) throw new Error(TEXT.pending);

  const s = await ctx.session.get({ sessionID }).catch(() => null);
  if (!s) throw new Error(TEXT.sessionGetFailed);

  const record = await readRecord(ctx, sessionID);
  let body;
  if (record && record.instruction) {
    if (s.revert && s.revert.messageID === record.boundaryMessageID) {
      // Stage intact and matching the record: safe to send.
      body = record.instruction;
    } else if (!s.revert) {
      // Distinguish "stage committed" from "stage cleared" via history: a commit removes the
      // boundary message and everything after from history, while a clear leaves the boundary
      // message (measured on v2.3.2: the list also returns hidden items while staged). Without
      // this discriminator, an apply after a CLI `--clear` would send an unintended re-prompt.
      const boundaryStill = (messages || []).some((m) => m && m.id === record.boundaryMessageID);
      if (boundaryStill) throw new Error(TEXT.clearedNotCommitted);
      const still = (messages || []).some((m) => m && m.id === record.questionMessageID);
      if (!still) throw new Error(TEXT.recordGone);
      body = record.instruction;
    } else {
      throw new Error(TEXT.foreignStage);
    }
  } else {
    // Record missing (server restart, CLI-staged, etc.). With no stage, do nothing (prevents an
    // unintended re-prompt after cancel). Only with a stage, re-derive from history and proceed
    // on an exact match (keeping the refuse-when-uncertain posture).
    if (!s.revert) throw new Error(TEXT.noStagedApply);
    const found = findLatestQuestion(messages);
    if (!found) throw new Error(TEXT.noQuestion);
    // Follow BOUNDARY_MODE (previously the work boundary was always recomputed, dead-ending
    // questionStep mode when the record was missing). Build the instruction with the same branch
    // as undoAnswer.
    const b = computeBoundary(messages, found.message);
    if (!b.ok) throw new Error(b.reason === "admin-only" ? TEXT.adminOnly : TEXT.noWork);
    if (s.revert.messageID !== b.message.id) throw new Error(TEXT.foreignStage);
    if (BOUNDARY_MODE === "questionStep") {
      body = lastUserTextBefore(messages, b.message);
      if (!body) throw new Error(TEXT.emptyReprompt);
    } else {
      try {
        body = buildInstruction(extractPayload(found.parts));
      } catch (e) {
        if (e instanceof PayloadTooLarge) throw new Error(TEXT.payloadTooLarge(e.message));
        throw e;
      }
    }
  }

  // The cap is measured in code points (same unit as the kernel; String.length counts UTF-16 code
  // units and would mis-refuse instructions containing emoji).
  if (!body || Array.from(body).length > MAX_INSTRUCTION_CHARS) throw new Error(TEXT.recordGone);

  try {
    await ctx.session.prompt({ sessionID, text: body });
  } catch (e) {
    throw new Error(TEXT.applyPromptFailed(e && e.message ? e.message : String(e)));
  }
  await dropRecord(ctx, sessionID);
  await say(ctx, sessionID, TEXT.applied);
}

// /undo-answer-cancel — clear the stage + drop the record.
async function undoCancel(ctx, sessionID) {
  gate(ctx);
  checkSessionID(sessionID);

  const s = await ctx.session.get({ sessionID }).catch(() => null);
  if (!s) throw new Error(TEXT.sessionGetFailed);
  const hadStage = Boolean(s.revert);
  // Read the staged files before clearing (no extra API call). If files is enabled but
  // revert.files is empty, the snapshot capture failed or the project is not a Git repository,
  // so file changes made while staged will not be returned.
  const record = hadStage ? await readRecord(ctx, sessionID).catch(() => null) : null;
  const stagedFiles = s.revert && Array.isArray(s.revert.files) ? s.revert.files : null;
  const filesStaged = (record && record.files === true) || Boolean(stagedFiles && stagedFiles.length > 0);
  const captureFailed = filesStaged && (!stagedFiles || stagedFiles.length === 0);
  if (hadStage) {
    try {
      await clearRevert(ctx.location.directory, sessionID);
    } catch (e) {
      throw new Error(TEXT.clearFailed(e && e.message ? e.message : String(e)));
    }
    const after = await ctx.session.get({ sessionID }).catch(() => null);
    if (after && after.revert) throw new Error(TEXT.clearFailed("revert still present after clear"));
  }
  await dropRecord(ctx, sessionID);
  const message = !hadStage ? TEXT.noStaged : captureFailed ? TEXT.cancelledFilesWarn : TEXT.cancelled;
  await say(ctx, sessionID, message);
}

export default Plugin.define({
  id: "question-undo",
  setup(ctx) {
    // An unknown BOUNDARY_MODE must not fall back to the safe side (questionStep) silently, so warn at registration.
    if (!KNOWN_BOUNDARY_MODES.includes(BOUNDARY_MODE)) {
      console.error(`question-undo: unknown BOUNDARY_MODE "${BOUNDARY_MODE}". /undo-answer will refuse with a boundary-computation failure.`);
    }
    // The version gate lives at execution time, not in setup (setup runs synchronously; a gate failure must not erase registration).
    ctx.command.transform((editor) => {
      editor.add({
        name: "undo-answer",
        description: TEXT.description,
        execute: async ({ sessionID }) => {
          await undoAnswer(ctx, sessionID);
        },
      });
      editor.add({
        name: "undo-answer-apply",
        description: TEXT.applyDescription,
        execute: async ({ sessionID }) => {
          await undoApply(ctx, sessionID);
        },
      });
      editor.add({
        name: "undo-answer-cancel",
        description: TEXT.cancelDescription,
        execute: async ({ sessionID }) => {
          await undoCancel(ctx, sessionID);
        },
      });
    });
  },
});
