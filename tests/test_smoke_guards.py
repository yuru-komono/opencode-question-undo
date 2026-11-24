"""test_smoke_guards.py — unit tests for the smoke.py flag guards (no server needed).

All guards fire before version_gate (the mutual-exclusion block in smoke.py), so sys.argv is
swapped and only the SystemExit message is verified. version_gate is mocked shut so a missing
guard never touches a real server.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import smoke


class TestFlagGuards(unittest.TestCase):
    def run_cli(self, *flags):
        with mock.patch.object(smoke, "version_gate", side_effect=AssertionError(f"reached version_gate without a guard: {flags}")), \
             mock.patch.object(sys, "argv", ["smoke.py", *flags]):
            try:
                smoke.main()
            except SystemExit as e:
                return e
        self.fail(f"the guard did not fire: {flags}")

    def assert_guard(self, exc, needle):
        self.assertIsInstance(exc.code, str)
        self.assertIn(needle, exc.code)

    def test_readonly_with_mutating(self):
        e = self.run_cli("--session", "s1", "--inspect", "--clear")
        self.assert_guard(e, "are read-only and cannot be combined")

    def test_clear_with_apply(self):
        e = self.run_cli("--session", "s1", "--clear", "--apply")
        self.assert_guard(e, "--clear only clears")

    def test_apply_with_commit(self):
        e = self.run_cli("--session", "s1", "--mode", "work", "--apply", "--commit")
        self.assert_guard(e, "--apply only sends")

    def test_apply_requires_work_mode(self):
        # The default flipped to work, so the guard fires only when question is explicitly combined.
        e = self.run_cli("--session", "s1", "--mode", "question", "--apply")
        self.assert_guard(e, "--apply must be combined with --mode work")

    def test_disposable_requires_measure(self):
        e = self.run_cli("--session", "s1", "--disposable")
        self.assert_guard(e, "--disposable must be combined with --measure-boundary")


class TestDefaultMode(unittest.TestCase):
    def _run_stage(self, extra_argv):
        # The default (no --mode) stages the v0.2.0 work boundary (the work message right after
        # the question), not the question message itself.
        q = {
            "id": "q1",
            "type": "assistant",
            "time": {"created": 100},
            "content": [
                {"type": "tool", "name": "question", "state": {"status": "completed", "input": {"questions": [{"question": "x", "options": []}]}}}
            ],
        }
        w = {"id": "w1", "type": "assistant", "time": {"created": 200}, "content": []}
        staged = {}

        def fake_api(method, path, data=None, timeout=180):
            if path.endswith("/revert/stage"):
                staged["messageID"] = data["messageID"]
                staged["files"] = data.get("files")
                return {}
            if method == "GET":
                return {"revert": dict(staged)} if staged else {}
            return {}

        with mock.patch.object(smoke, "version_gate"), \
             mock.patch.object(smoke, "fetch_messages", return_value=[w, q]), \
             mock.patch.object(smoke, "api", side_effect=fake_api), \
             mock.patch.object(smoke.Path, "cwd", return_value=Path(tempfile.gettempdir())), \
             mock.patch.object(sys, "argv", ["smoke.py", "--session", "s1", *extra_argv]):
            rc = smoke.main()
        return rc, staged

    def test_default_stages_work_boundary(self):
        rc, staged = self._run_stage([])
        self.assertEqual(rc, 0)
        self.assertEqual(staged.get("messageID"), "w1")  # the work message, not q1, is the boundary
        self.assertIs(staged.get("files"), False)  # the default is files:false (no file rollback)

    def test_files_flag_sets_stage_payload(self):
        # --files sets files:true in the stage payload (overriding the default False).
        rc, staged = self._run_stage(["--files"])
        self.assertEqual(rc, 0)
        self.assertIs(staged.get("files"), True)


class TestVersionGate(unittest.TestCase):
    """The matrix of version_gate(allow_drift, readonly) (api is mocked; no real server. v0.7.0 set basis)."""

    def run_gate(self, server_version, allow_drift=False, readonly=False, files=False):
        err = io.StringIO()
        with mock.patch.object(smoke, "api", return_value={"version": server_version}), \
             contextlib.redirect_stderr(err):
            try:
                smoke.version_gate(allow_drift, readonly, files)
                raised = None
            except SystemExit as e:
                raised = e
        return raised, err.getvalue()

    def test_same_silent(self):
        raised, err = self.run_gate(smoke.PINNED_VERSION)
        self.assertIsNone(raised)
        self.assertEqual(err, "")

    def test_every_verified_member_is_silent(self):
        # v0.7.0: the basis is the verified set, not a single pin (2.3.2 and 2.4.0 must not be refused)
        self.assertGreaterEqual(len(smoke.VERIFIED_VERSIONS), 2)  # an empty set makes the loop vacuous (L4)
        for v in smoke.VERIFIED_VERSIONS:
            raised, err = self.run_gate(v)
            self.assertIsNone(raised, f"verified version refused: {v}")
            self.assertEqual(err, "", f"warning printed for a verified version: {v}")

    def test_files_notice_fires_on_verified_but_unmeasured_version(self):
        # file rollback is measured on PINNED_VERSION; 2.3.2 became "same" in v0.7.0 but the files
        # notice must not disappear there (review M1)
        raised, err = self.run_gate("2.3.2", files=True)
        self.assertIsNone(raised)
        self.assertIn("files:true", err)

    def test_files_notice_silent_on_the_pin(self):
        raised, err = self.run_gate(smoke.PINNED_VERSION, files=True)
        self.assertIsNone(raised)
        self.assertEqual(err, "")

    def test_unverified_between_min_and_max_warns_and_runs(self):
        raised, err = self.run_gate("2.3.9")
        self.assertIsNone(raised)
        self.assertIn("[warning]", err)
        self.assertIn("unverified", err)

    def test_newer_warns_and_runs(self):
        raised, err = self.run_gate("99.0.0")
        self.assertIsNone(raised)
        self.assertIn("[warning]", err)

    def test_unknown_warns_and_runs(self):
        raised, err = self.run_gate("2.3.2-beta.1")
        self.assertIsNone(raised)
        self.assertIn("[warning]", err)

    def test_numeric_segments_not_lexicographic(self):
        # 2.10.0 is newer (string comparison would read "2.10.0" < "2.3.2" and refuse wrongly)
        raised, err = self.run_gate("2.10.0")
        self.assertIsNone(raised)
        self.assertIn("[warning]", err)

    def test_older_rejects_mutating(self):
        raised, err = self.run_gate("2.3.1")
        self.assertIsNotNone(raised)
        self.assertIn("[version gate]", str(raised.code))

    def test_older_readonly_warns(self):
        raised, err = self.run_gate("2.3.1", readonly=True)
        self.assertIsNone(raised)
        self.assertIn("[warning]", err)

    def test_older_with_flag_warns(self):
        raised, err = self.run_gate("2.3.1", allow_drift=True)
        self.assertIsNone(raised)
        self.assertIn("[warning]", err)


if __name__ == "__main__":
    unittest.main()
