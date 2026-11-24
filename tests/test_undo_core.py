"""test_undo_core.py — unit tests for undo_core (unittest, standard library only).

The fixtures are hand-mirrored with the JS side in tests/undo-kernel.test.js (update both when
a rule changes).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import undo_core


def msg(mid, mtype, created, **extra):
    m = {"id": mid, "type": mtype, "time": {"created": created}, "content": []}
    m.update(extra)
    return m


class TestSortKey(unittest.TestCase):
    def test_time_created_is_primary(self):
        # The measured fork shape: lexicographically "_544" < "_58" but chronologically the reverse (v0.2.0 measurement).
        a = msg("msg_A_544", "assistant", 100)
        b = msg("msg_A_58", "assistant", 200)
        self.assertLess(undo_core.sort_key(a), undo_core.sort_key(b))

    def test_same_created_compares_suffix_numerically(self):
        a = msg("msg_A_58", "assistant", 100)
        b = msg("msg_A_544", "assistant", 100)
        self.assertLess(undo_core.sort_key(a), undo_core.sort_key(b))
        c = msg("msg_B_1", "assistant", 100)
        self.assertLess(undo_core.sort_key(a), undo_core.sort_key(c))


class TestComputeWorkBoundary(unittest.TestCase):
    def test_raw_successor(self):
        q = msg("q", "assistant", 100)
        w = msg("w", "assistant", 200)
        r = undo_core.compute_work_boundary([w, q], q)  # deliberately reversed order
        self.assertEqual(r["rule"], "raw-successor")
        self.assertEqual(r["message"]["id"], "w")

    def test_skip_idle_to_first_work(self):
        q = msg("q", "assistant", 100)
        idle = msg("i", "idle", 150, outcome="succeeded")
        w = msg("w", "assistant", 200)
        r = undo_core.compute_work_boundary([q, idle, w], q)
        self.assertEqual(r["rule"], "skip-idle-to-first-work")
        self.assertEqual(r["message"]["id"], "w")

    def test_admin_types_are_not_boundary(self):
        q = msg("q", "assistant", 100)
        comp = msg("c", "compaction", 150)
        shell = msg("s", "shell", 160)
        w = msg("w", "assistant", 200)
        r = undo_core.compute_work_boundary([q, comp, shell, w], q)
        self.assertEqual(r["message"]["id"], "w")

    def test_no_work_and_admin_only(self):
        q = msg("q", "assistant", 100)
        self.assertEqual(undo_core.compute_work_boundary([q], q), {"ok": False, "reason": "no-work"})
        idle = msg("i", "idle", 150, outcome="succeeded")
        syn = msg("s", "synthetic", 160)
        r = undo_core.compute_work_boundary([q, idle, syn], q)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "admin-only")


class TestEscapeSentinels(unittest.TestCase):
    def test_zwsp_inserted_and_variants_caught(self):
        out = undo_core.escape_sentinels("x [q_undo-end-payload] y")
        self.assertIn("q_undo\u200b-end-payload", out)
        self.assertNotIn("q_undo-end-payload", out.lower())

    def test_length_changing_char_before_token(self):
        out = undo_core.escape_sentinels("İ[q_undo-begin-payload]")
        self.assertIn("İ[q_undo\u200b-begin-payload]", out)

    def test_multiple_occurrences(self):
        out = undo_core.escape_sentinels("[q_undo-begin-payload]..[q_undo-begin-payload]")
        self.assertEqual(out.lower().count("q_undo-begin-payload"), 0)

    def test_many_occurrences_keep_zwsp_position(self):
        # Regression for review finding H1: reusing pre-mutation indices leaves the token intact
        # from the 7th occurrence on. With 8 consecutive occurrences assert (a) no intact token
        # remains and (b) the ZWSP sits right after q_undo.
        out = undo_core.escape_sentinels("[q_undo-end-payload]" * 8)
        self.assertEqual(out.lower().count("q_undo-end-payload"), 0)
        self.assertEqual(out.count("q_undo\u200b-end-payload"), 8)


def question_part(n):
    return {
        "type": "tool",
        "name": "question",
        "state": {
            "status": "completed",
            "input": {
                "questions": [
                    {"question": f"q{i}", "header": f"h{i}", "multiple": False, "options": [{"label": "a", "description": "b"}]}
                    for i in range(n)
                ]
            },
        },
    }


class TestCaps(unittest.TestCase):
    def test_extract_payload_caps(self):
        with self.assertRaises(undo_core.PayloadTooLarge):
            undo_core.extract_payload([question_part(undo_core.MAX_QUESTIONS_PER_PART + 1)])
        many = {"state": {"input": {"questions": [{"options": [{"label": "x"} for _ in range(undo_core.MAX_OPTIONS_PER_QUESTION + 1)]}]}}}
        with self.assertRaises(undo_core.PayloadTooLarge):
            undo_core.extract_payload([many])
        long_q = {"state": {"input": {"questions": [{"question": "あ" * (undo_core.MAX_STRING_CHARS + 1)}]}}}
        with self.assertRaises(undo_core.PayloadTooLarge):
            undo_core.extract_payload([long_q])
        long_opt = {"state": {"input": {"questions": [{"options": [{"description": "い" * (undo_core.MAX_STRING_CHARS + 1)}]}]}}}
        with self.assertRaises(undo_core.PayloadTooLarge):
            undo_core.extract_payload([long_opt])

    def test_build_instruction_cap(self):
        big = [
            {
                "questions": [
                    {"question": "う" * undo_core.MAX_STRING_CHARS, "header": "", "multiple": False, "options": []}
                    for _ in range(undo_core.MAX_QUESTIONS_PER_PART)
                ]
            }
        ]
        with self.assertRaises(undo_core.PayloadTooLarge):
            undo_core.build_instruction(big)

    def test_build_instruction_normal(self):
        text = undo_core.build_instruction(undo_core.extract_payload([question_part(1)]))
        self.assertIn("[q_undo-begin-payload]", text)
        self.assertIn("[q_undo-end-payload]", text)


class TestLastUserTextBefore(unittest.TestCase):
    def test_text_field_preferred(self):
        u = msg("u", "user", 50, text="  body  ")
        self.assertEqual(undo_core.last_user_text_before([u], msg("b", "assistant", 100)), "body")

    def test_content_fallback(self):
        u = msg("u", "user", 50, content=[{"type": "text", "text": "fallback"}])
        self.assertEqual(undo_core.last_user_text_before([u], msg("b", "assistant", 100)), "fallback")

    def test_none_before_boundary(self):
        u = msg("u", "user", 150, text="after")
        self.assertEqual(undo_core.last_user_text_before([u], msg("b", "assistant", 100)), "")


class TestFindLatestQuestion(unittest.TestCase):
    def test_completed_only_and_order_independent(self):
        q1 = msg("q1", "assistant", 100, content=[{"type": "tool", "name": "question", "state": {"status": "completed", "input": {"questions": []}}}])
        q2 = msg("q2", "assistant", 200, content=[{"type": "tool", "name": "question", "state": {"status": "completed", "input": {"questions": []}}}])
        pending = msg("p", "assistant", 300, content=[{"type": "tool", "name": "question", "state": {"status": "running"}}])
        found = undo_core.find_latest_question([pending, q1, q2])
        self.assertEqual(found["message"]["id"], "q2")


class TestTailOutcome(unittest.TestCase):
    def test_outcome(self):
        q = msg("q", "assistant", 100)
        w = msg("w", "assistant", 200)
        idle = msg("i", "idle", 300, outcome="interrupted")
        self.assertEqual(undo_core.tail_outcome([q, w, idle], q), "interrupted")
        self.assertIsNone(undo_core.tail_outcome([q, w], q))
        self.assertIsNone(undo_core.tail_outcome([q], q))


class TestAdminTypes(unittest.TestCase):
    def test_membership(self):
        for t in ("idle", "system", "compaction", "skill", "shell", "synthetic", "agent-switched", "model-switched", "location-switched"):
            self.assertIn(t, undo_core.ADMIN_TYPES)
        self.assertNotIn("assistant", undo_core.ADMIN_TYPES)
        self.assertNotIn("user", undo_core.ADMIN_TYPES)


class TestCompareVersions(unittest.TestCase):
    """The four version-gate verdict tokens (hand-mirrored table with tests/undo-kernel.test.js)."""

    def test_verdicts(self):
        self.assertEqual(undo_core.compare_versions("2.3.2", "2.3.2"), "same")
        self.assertEqual(undo_core.compare_versions("2.4.0", "2.3.2"), "newer")
        self.assertEqual(undo_core.compare_versions("2.3.1", "2.3.2"), "older")
        self.assertEqual(undo_core.compare_versions("2.2.9", "2.3.2"), "older")
        # numeric segment comparison (lexicographic order would get these wrong)
        self.assertEqual(undo_core.compare_versions("2.10.0", "2.3.2"), "newer")
        self.assertEqual(undo_core.compare_versions("3.0.0", "2.99.99"), "newer")

    def test_unknown_forms(self):
        # trailing newline and Unicode digits pin the Python engine-leniency trap (review finding M1)
        for v in ("2.3.2-beta.1", "2.3", "2.3.2.1", "", "v2.3.2", " 2.3.2", "2.3.1\n", "٢.٣.٢", None, 2.32, {}):
            self.assertEqual(undo_core.compare_versions(v, "2.3.2"), "unknown")
        # a malformed pin side is unknown too (the parity gate #7 shape guard prevents it upstream)
        self.assertEqual(undo_core.compare_versions("2.3.2", "2.3"), "unknown")


class TestGateVerdict(unittest.TestCase):
    """Version-gate acceptance basis (v0.7.0; hand-mirrored table with tests/undo-kernel.test.js)."""

    def test_members_of_verified_set_are_same(self):
        # an empty set would make the loop vacuous (boundary values pinned individually: review L4)
        self.assertGreaterEqual(len(undo_core.VERIFIED_VERSIONS), 2)
        for v in undo_core.VERIFIED_VERSIONS:
            self.assertEqual(undo_core.gate_verdict(v, undo_core.VERIFIED_VERSIONS), "same")
        self.assertEqual(undo_core.gate_verdict("2.3.2", undo_core.VERIFIED_VERSIONS), "same")
        self.assertEqual(undo_core.gate_verdict("2.4.0", undo_core.VERIFIED_VERSIONS), "same")

    def test_newer_and_older_than_the_set(self):
        self.assertEqual(undo_core.gate_verdict("2.4.2", undo_core.VERIFIED_VERSIONS), "newer")
        self.assertEqual(undo_core.gate_verdict("2.10.0", undo_core.VERIFIED_VERSIONS), "newer")
        self.assertEqual(undo_core.gate_verdict("2.3.1", undo_core.VERIFIED_VERSIONS), "older")
        self.assertEqual(undo_core.gate_verdict("2.2.9", undo_core.VERIFIED_VERSIONS), "older")

    def test_unverified_between_min_and_max(self):
        # the versions around it are verified, so an unlisted one in between is expected to work
        self.assertEqual(undo_core.gate_verdict("2.3.9", undo_core.VERIFIED_VERSIONS), "unverified")
        self.assertEqual(undo_core.gate_verdict("2.3.3", undo_core.VERIFIED_VERSIONS), "unverified")

    def test_unknown_forms(self):
        for v in ("2.3.2-beta.1", "2.3", "", "v2.3.2", None, 2.32, {}):
            self.assertEqual(undo_core.gate_verdict(v, undo_core.VERIFIED_VERSIONS), "unknown")
        # an empty set drops the older refusal (fail-open); parity check #14 stops it upstream, and
        # this function's contract only reaches "returns unknown" (review L3)
        self.assertEqual(undo_core.gate_verdict("2.4.1", ()), "unknown")
        self.assertEqual(undo_core.gate_verdict("2.4.1", ("2.3",)), "unknown")
        # a set argument that is not a list/tuple is unknown (same as the JS Array.isArray guard: L1)
        for bad in (None, "2.3.2", 2.32, {}):
            self.assertEqual(undo_core.gate_verdict("2.4.1", bad), "unknown")

    def test_alternate_spelling_of_the_minimum_is_not_refused(self):
        # VERSION_RE accepts leading zeros; missing the string match must not become a refusal (L2)
        self.assertEqual(undo_core.gate_verdict("2.3.02", undo_core.VERIFIED_VERSIONS), "unverified")
        self.assertEqual(undo_core.gate_verdict("2.3.1", undo_core.VERIFIED_VERSIONS), "older")

    def test_order_independent(self):
        shuffled = ("2.4.1", "2.3.2", "2.4.0")
        self.assertEqual(undo_core.gate_verdict("2.3.9", shuffled), "unverified")
        self.assertEqual(undo_core.gate_verdict("2.2.0", shuffled), "older")
        self.assertEqual(undo_core.gate_verdict("9.0.0", shuffled), "newer")


class TestResolveFilesMode(unittest.TestCase):
    """Effective file-rollback mode of the opt-in (hand-mirrored table with tests/undo-kernel.test.js)."""

    def test_priority_or_semantics(self):
        # All three inputs are "enable" signals: any True gives True, only all False gives False.
        self.assertTrue(undo_core.resolve_files_mode(True, False, False))
        self.assertTrue(undo_core.resolve_files_mode(False, True, False))
        self.assertTrue(undo_core.resolve_files_mode(False, False, True))
        self.assertTrue(undo_core.resolve_files_mode(True, True, True))
        self.assertFalse(undo_core.resolve_files_mode(False, False, False))

    def test_non_bool_normalized(self):
        # non-bool values are normalized by bool() (None / 0 / "" count as False).
        self.assertFalse(undo_core.resolve_files_mode(None, None, None))
        self.assertTrue(undo_core.resolve_files_mode(None, True, None))
        self.assertTrue(undo_core.resolve_files_mode(0, 0, 1))


if __name__ == "__main__":
    unittest.main()
