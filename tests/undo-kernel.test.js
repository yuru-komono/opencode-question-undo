// undo-kernel.test.js — unit tests for the pure logic (node:test, zero added dependencies).
// The boundary rules, fork ordering, sentinel escape, cap gates and version verdicts are
// hand-mirrored between the JS and Python sides, so the same fixtures live in
// tests/test_undo_core.py (update both when a rule changes).

import test from "node:test";
import assert from "node:assert/strict";
import {
  ADMIN_TYPES,
  MAX_INSTRUCTION_CHARS,
  MAX_OPTIONS_PER_QUESTION,
  MAX_QUESTIONS_PER_PART,
  MAX_STRING_CHARS,
  PayloadTooLarge,
  VERIFIED_VERSIONS,
  buildInstruction,
  compareMessages,
  compareVersions,
  computeWorkBoundary,
  escapeSentinels,
  extractPayload,
  gateVerdict,
  resolveFilesMode,
  tailOutcome,
} from "../src/undo-kernel.js";

const msg = (id, type, created, extra = {}) => ({ id, type, time: { created }, content: [], ...extra });

test("compareMessages: time.created is the primary key (the measured fork shape breaks lexicographic order)", () => {
  const a = msg("msg_A_544", "assistant", 100);
  const b = msg("msg_A_58", "assistant", 200);
  // Lexicographically "_544" < "_58", but chronologically b is later (measured on v0.2.0).
  assert.ok(compareMessages(a, b) < 0);
  assert.ok(compareMessages(b, a) > 0);
  assert.equal(compareMessages(a, a), 0);
});

test("compareMessages: same created compares same-base suffixes numerically", () => {
  const a = msg("msg_A_58", "assistant", 100);
  const b = msg("msg_A_544", "assistant", 100);
  assert.ok(compareMessages(a, b) < 0); // 58 < 544 numerically (lexicographic order would flip it)
  const c = msg("msg_B_1", "assistant", 100);
  assert.ok(compareMessages(a, c) < 0); // different bases compare lexicographically
});

test("computeWorkBoundary: the work message right after becomes the boundary (raw-successor, independent of list order)", () => {
  const q = msg("q", "assistant", 100);
  const w = msg("w", "assistant", 200);
  const r = computeWorkBoundary([w, q], q); // deliberately reversed order
  assert.equal(r.ok, true);
  assert.equal(r.message.id, "w");
  assert.equal(r.rule, "raw-successor");
});

test("computeWorkBoundary: an idle right after skips to the first work (skip-idle-to-first-work)", () => {
  const q = msg("q", "assistant", 100);
  const idle = msg("i", "idle", 150, { outcome: "succeeded" });
  const w = msg("w", "assistant", 200);
  const r = computeWorkBoundary([q, idle, w], q);
  assert.equal(r.ok, true);
  assert.equal(r.message.id, "w");
  assert.equal(r.rule, "skip-idle-to-first-work");
});

test("computeWorkBoundary: non-idle admin types are never the boundary (regression for review finding M1)", () => {
  const q = msg("q", "assistant", 100);
  const comp = msg("c", "compaction", 150);
  const shell = msg("s", "shell", 160);
  const w = msg("w", "assistant", 200);
  const r = computeWorkBoundary([q, comp, shell, w], q);
  assert.equal(r.message.id, "w");
  assert.equal(r.rule, "skip-idle-to-first-work");
});

test("computeWorkBoundary: no successor is no-work, admin-only tail is admin-only", () => {
  const q = msg("q", "assistant", 100);
  assert.deepEqual(computeWorkBoundary([q], q), { ok: false, reason: "no-work" });
  const idle = msg("i", "idle", 150, { outcome: "succeeded" });
  const syn = msg("s", "synthetic", 160);
  const r = computeWorkBoundary([q, idle, syn], q);
  assert.equal(r.ok, false);
  assert.equal(r.reason, "admin-only");
});

test("tailOutcome: returns the outcome of a tail idle message, otherwise null", () => {
  const q = msg("q", "assistant", 100);
  const w = msg("w", "assistant", 200);
  const idle = msg("i", "idle", 300, { outcome: "interrupted" });
  assert.equal(tailOutcome([q, w, idle], q), "interrupted");
  assert.equal(tailOutcome([q, w], q), null);
  assert.equal(tailOutcome([q], q), null);
});

test("escapeSentinels: inserts U+200B into the closing sentinel and catches case variants", () => {
  const out = escapeSentinels("x [q_undo-end-payload] y");
  assert.ok(out.includes("q_undo\u200b-end-payload"));
  assert.equal(/q_undo-end-payload/i.test(out), false);
  const upper = escapeSentinels("[Q_UNDO-BEGIN-PAYLOAD]");
  assert.ok(upper.includes("Q_UNDO\u200b-BEGIN-PAYLOAD")); // original case is kept; ZWSP lands at the q_undo-length offset
});

test("escapeSentinels: a length-changing character before the token does not shift the cut (regression for review finding L3)", () => {
  const out = escapeSentinels("İ[q_undo-begin-payload]");
  assert.ok(out.includes("İ[q_undo\u200b-begin-payload]"));
});

test("escapeSentinels: neutralizes every occurrence", () => {
  const out = escapeSentinels("[q_undo-begin-payload]..[q_undo-begin-payload]");
  assert.equal((out.match(/q_undo-begin-payload/gi) || []).length, 0);
});

test("escapeSentinels: 8 consecutive occurrences all get the ZWSP at the right offset (regression for review finding H1, pinning the JS side)", () => {
  const out = escapeSentinels("[q_undo-end-payload]".repeat(8));
  assert.equal((out.match(/q_undo-end-payload/gi) || []).length, 0);
  assert.equal(out.split("q_undo\u200b-end-payload").length - 1, 8);
});

const questionPart = (n) => ({
  type: "tool",
  name: "question",
  state: {
    status: "completed",
    input: {
      questions: Array.from({ length: n }, (_, i) => ({
        question: `q${i}`,
        header: `h${i}`,
        multiple: false,
        options: [{ label: "a", description: "b" }],
      })),
    },
  },
});

test("extractPayload: carries question/header/multiple/options verbatim (missing fields become empty)", () => {
  const part = {
    type: "tool",
    name: "question",
    state: {
      status: "completed",
      input: {
        questions: [
          { question: "Which one?", header: "Plan", multiple: true, options: [{ label: "A", description: "Plan A" }, { label: "B" }] },
        ],
      },
    },
  };
  const [call] = extractPayload([part]);
  assert.deepEqual(call.questions, [
    { question: "Which one?", header: "Plan", multiple: true, options: [{ label: "A", description: "Plan A" }, { label: "B", description: "" }] },
  ]);
});

test("extractPayload: cap violations raise PayloadTooLarge instead of silent truncation", () => {
  assert.throws(() => extractPayload([questionPart(MAX_QUESTIONS_PER_PART + 1)]), PayloadTooLarge);
  const manyOptions = {
    state: { input: { questions: [{ options: Array.from({ length: MAX_OPTIONS_PER_QUESTION + 1 }, () => ({ label: "x" })) }] } },
  };
  assert.throws(() => extractPayload([manyOptions]), PayloadTooLarge);
  const longStr = { state: { input: { questions: [{ question: "あ".repeat(MAX_STRING_CHARS + 1) }] } } };
  assert.throws(() => extractPayload([longStr]), PayloadTooLarge);
  const longOpt = { state: { input: { questions: [{ options: [{ description: "い".repeat(MAX_STRING_CHARS + 1) }] }] } } };
  assert.throws(() => extractPayload([longOpt]), PayloadTooLarge);
});

test("buildInstruction: wraps the payload in sentinels and refuses over-cap instructions", () => {
  const text = buildInstruction(extractPayload([questionPart(1)]));
  assert.ok(text.includes("[q_undo-begin-payload]"));
  assert.ok(text.includes("[q_undo-end-payload]"));
  assert.ok(Array.from(text).length <= MAX_INSTRUCTION_CHARS);
  const big = [
    {
      questions: Array.from({ length: MAX_QUESTIONS_PER_PART }, () => ({
        question: "う".repeat(MAX_STRING_CHARS),
        header: "",
        multiple: false,
        options: [],
      })),
    },
  ];
  assert.throws(() => buildInstruction(big), PayloadTooLarge);
});

test("ADMIN_TYPES: run markers, system injections, compaction and synthetic are not work", () => {
  for (const t of ["idle", "system", "compaction", "skill", "shell", "synthetic", "agent-switched", "model-switched", "location-switched"]) {
    assert.ok(ADMIN_TYPES.has(t), `ADMIN_TYPES lacks ${t}`);
  }
  assert.equal(ADMIN_TYPES.has("assistant"), false);
  assert.equal(ADMIN_TYPES.has("user"), false);
});

test("compareVersions: four verdict tokens and numeric segment comparison (the 2.10.0 vs 2.3.2 lexicographic trap)", () => {
  assert.equal(compareVersions("2.3.2", "2.3.2"), "same");
  assert.equal(compareVersions("2.4.0", "2.3.2"), "newer");
  assert.equal(compareVersions("2.3.1", "2.3.2"), "older");
  assert.equal(compareVersions("2.2.9", "2.3.2"), "older");
  assert.equal(compareVersions("2.10.0", "2.3.2"), "newer"); // numeric (lexicographic would say older)
  assert.equal(compareVersions("3.0.0", "2.99.99"), "newer");
});

test("compareVersions: unparseable forms are unknown (suffixes, dev builds, empty, non-strings)", () => {
  // trailing newline and Unicode digits pin the Python engine-leniency trap (review finding M1; JS was always strict)
  for (const v of ["2.3.2-beta.1", "2.3", "2.3.2.1", "", "v2.3.2", " 2.3.2", "2.3.1\n", "٢.٣.٢", undefined, null, 2.32, {}]) {
    assert.equal(compareVersions(v, "2.3.2"), "unknown", `expected unknown: ${String(v)}`);
  }
  // a malformed pin side is unknown too (the parity gate #7 shape guard prevents it upstream)
  assert.equal(compareVersions("2.3.2", "2.3"), "unknown");
});

test("gateVerdict: members of the verified set are same (the v0.7.0 acceptance basis)", () => {
  // an empty set would make the loop vacuous (the boundary values are pinned individually: review L4)
  assert.ok(VERIFIED_VERSIONS.length >= 2, `verified set too small: ${JSON.stringify(VERIFIED_VERSIONS)}`);
  for (const v of VERIFIED_VERSIONS) {
    assert.equal(gateVerdict(v, VERIFIED_VERSIONS), "same", `expected same: ${v}`);
  }
  assert.equal(gateVerdict("2.3.2", VERIFIED_VERSIONS), "same");
  assert.equal(gateVerdict("2.4.0", VERIFIED_VERSIONS), "same");
});

test("gateVerdict: newer than the newest verified version is newer, older than the oldest is older", () => {
  assert.equal(gateVerdict("2.4.2", VERIFIED_VERSIONS), "newer");
  assert.equal(gateVerdict("2.10.0", VERIFIED_VERSIONS), "newer"); // numeric (lexicographic would say older)
  assert.equal(gateVerdict("2.3.1", VERIFIED_VERSIONS), "older");
  assert.equal(gateVerdict("2.2.9", VERIFIED_VERSIONS), "older");
  assert.equal(gateVerdict("2.3.2", VERIFIED_VERSIONS), "same"); // the oldest entry itself
  assert.equal(gateVerdict("2.4.1", VERIFIED_VERSIONS), "same"); // the newest entry itself
});

test("gateVerdict: between the oldest and the newest but not listed is unverified (warns and runs)", () => {
  assert.equal(gateVerdict("2.3.9", VERIFIED_VERSIONS), "unverified");
  assert.equal(gateVerdict("2.3.3", VERIFIED_VERSIONS), "unverified");
});

test("gateVerdict: unparseable forms, an empty set and a non-array set are unknown (callers warn and run)", () => {
  for (const v of ["2.3.2-beta.1", "2.3", "", "v2.3.2", undefined, null, 2.32, {}]) {
    assert.equal(gateVerdict(v, VERIFIED_VERSIONS), "unknown", `expected unknown: ${String(v)}`);
  }
  // an empty set drops the older refusal (fail-open); parity check #14 is what stops it upstream,
  // and this function's contract only reaches "returns unknown" (review L3)
  assert.equal(gateVerdict("2.4.1", []), "unknown");
  assert.equal(gateVerdict("2.4.1", ["2.3"]), "unknown"); // a malformed set side is unknown too
  // a non-array set argument is unknown (same treatment as the Python list/tuple guard: review L1)
  for (const bad of [undefined, null, "2.3.2", 2.32, {}]) {
    assert.equal(gateVerdict("2.4.1", bad), "unknown", `expected unknown: ${String(bad)}`);
  }
});

test("gateVerdict: an alternate spelling of the minimum (2.3.02) is not refused, it is unverified", () => {
  // VERSION_RE accepts leading zeros; missing the string match must not become a refusal (review L2)
  assert.equal(gateVerdict("2.3.02", VERIFIED_VERSIONS), "unverified");
  assert.equal(gateVerdict("2.3.1", VERIFIED_VERSIONS), "older"); // genuinely older still refuses
});

test("gateVerdict: independent of the order of the set (lo/hi are found with the comparator)", () => {
  const shuffled = ["2.4.1", "2.3.2", "2.4.0"];
  assert.equal(gateVerdict("2.3.9", shuffled), "unverified");
  assert.equal(gateVerdict("2.2.0", shuffled), "older");
  assert.equal(gateVerdict("9.0.0", shuffled), "newer");
});

test("resolveFilesMode: precedence truth table (flag > marker > constant)", () => {
  // All three inputs are "enable" signals: any true gives true, only all false gives false.
  assert.equal(resolveFilesMode(true, false, false), true);
  assert.equal(resolveFilesMode(false, true, false), true);
  assert.equal(resolveFilesMode(false, false, true), true);
  assert.equal(resolveFilesMode(true, true, true), true);
  assert.equal(resolveFilesMode(false, false, false), false);
  // non-bool input is normalized by Boolean() (undefined / 0 / "" count as false).
  assert.equal(resolveFilesMode(undefined, undefined, undefined), false);
  assert.equal(resolveFilesMode(undefined, true, undefined), true);
  assert.equal(resolveFilesMode(0, 0, 1), true);
});
