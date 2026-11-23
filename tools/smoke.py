"""smoke.py — CLI version of the question redo (fallback and drift check).

Default is revert/stage only (reversible). Re-presentation after staging goes through the
shared `/undo-answer-apply` command (Desktop, Web UI, TUI) or this CLI's `--mode work --apply`.
Writing the instruction into the composer was removed in v0.3.0. To only read the instruction,
use `python tools/smoke.py --session <sid> --mode work --print-prompt` (read-only). Note:
sending a new message while staged commits the stage (unrecoverable).
Clear with --clear or /undo-answer-cancel.
Irreversible commit is only done with the explicit `--commit --reprompt` flags.

Modes:
  --mode work      (default) v0.2.0 behavior. The boundary is the first work message right
                   after the answered question (only the later work disappears) and the
                   instruction re-presents the same question verbatim.
  --mode question  v0.1.0 behavior. The boundary is the message containing the answered
                   question, and the previous user message is re-sent.

Read-only (safe on active sessions):
  --list                     list sessions (id and title)
  --session <sid> --inspect  print the layout right after the answered question, the computed
                             boundary, and the tail run state
  --session <sid> --print-prompt  print the re-send body per --mode to stdout (work=instruction /
                             question=previous user message; no staging)
Sending (CLI equivalent of the GUI's /undo-answer-apply):
  --session <sid> --mode work --apply
                             stage verification + send the instruction (sending commits the
                             stage and re-presents the question)
                             works even with no stage (e.g. committed by an accidental send)
                             as long as the question is still in history
                             this command does not read the plugin record (ctx.storage), so
                             the instruction is recomputed from history
Measurement with changes (disposable sessions only):
  --session <sid> --mode work --measure-boundary --disposable
                             stage -> observe revert state and list diff -> auto clear
                             (no commit)

Usage:
  python tools/smoke.py --list
  python tools/smoke.py --session <sid> --inspect
  python tools/smoke.py --session <sid>                      # stage at the default boundary (work mode)
  python tools/smoke.py --session <sid> --mode question      # stage at the v0.1.0 boundary (questionStep)
  python tools/smoke.py --session <sid> --clear              # clear the staged revert
  python tools/smoke.py --session <sid> --mode work --apply  # send the instruction (/undo-answer-apply equivalent)
  python tools/smoke.py --session <sid> --mode work --commit --reprompt   # delete then re-send (irreversible)

Version gate (v0.5.0): a server newer than the verified PINNED_VERSION, or an unparseable
version, warns and runs; an older server is refused. Read-only modes run with a warning even
on older servers (the re-verification ritual must not be blocked). --allow-version-drift is
the explicit escape hatch for older servers.
"""

import argparse
import re
import sys

from fetch_api import ApiError, api
from undo_core import (
    PayloadTooLarge,
    build_instruction,
    compare_versions,
    compute_work_boundary,
    describe,
    describe_boundary,
    extract_payload,
    find_latest_question,
    last_user_text_before,
    render_inspect_table,
    tail_outcome,
)

# Console encoding guard: when stdout is a pipe, the locale encoding (e.g. cp932) becomes the
# default, and printing a session title with an unencodable character (U+2014 etc.) crashes with
# UnicodeEncodeError. errors="replace" swaps only unencodable characters for ? (v0.5.1).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

PINNED_VERSION = "2.4.0"
SID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# message.list default page is the newest 50 (measured on v2.3.2). limit=1000 returns HTTP 400, so use 200.
MSG_QUERY = "?limit=200"


def fetch_messages(sid):
    """Fetch message.list with an explicit limit (the default page holds only the newest 50)."""
    d = api("GET", f"/api/session/{sid}/message{MSG_QUERY}")
    return d.get("data") if isinstance(d, dict) else d


def display_version(v):
    """Display-layer guard: the version string is API-supplied. Show printable ASCII ≤32 chars only, else "unknown" (log-injection prevention).

    Mirror: DISPLAY_VERSION_RE in src/undo-server.js — a hand-mirrored pair; update both sides together.
    """
    if isinstance(v, str) and re.fullmatch(r"[\x20-\x7e]{1,32}", v):
        return v
    return "unknown"


def version_gate(allow_drift, readonly):
    """Runtime version gate (v0.5.0 policy).

    same → silent pass. newer / unknown (unparseable) → warn and run.
    older → mutating modes refuse (--allow-version-drift downgrades the refusal to a warning).
    Read-only modes (--list / --inspect / --print-prompt) warn and run even on older servers
    (so the re-verification ritual is not blocked). Warnings go to stderr (stdout stays clean
    for --print-prompt).
    """
    info = api("GET", "/api/info")
    version = (info or {}).get("version")
    verdict = compare_versions(version, PINNED_VERSION)
    if verdict == "same":
        return
    msg = f"server version {display_version(version)} differs from the verified {PINNED_VERSION} (verdict {verdict})"
    if verdict == "older" and not allow_drift and not readonly:
        raise SystemExit(
            f"[version gate] {msg}. Refusing to run on a server older than the verified version. "
            "--allow-version-drift bypasses it (at your own risk)."
        )
    print(f"[warning] {msg}", file=sys.stderr)


def has_pending_question(messages):
    # Restricting to assistant mirrors hasPendingQuestion on the JS side (review finding L4).
    return any(
        m.get("type") == "assistant"
        and p.get("type") == "tool"
        and p.get("name") == "question"
        and (p.get("state") or {}).get("status") != "completed"
        for m in messages or []
        if m
        for p in (m.get("content") or [])
    )


def select_boundary(messages, found, mode):
    """Boundary per mode. Returns (boundary_id, info dict)."""
    if mode == "question":
        return found["message"]["id"], {"ok": True, "message": found["message"], "rule": "questionStep"}
    b = compute_work_boundary(messages, found["message"])
    if not b.get("ok"):
        return None, b
    return b["message"]["id"], b


def message_ids(sid):
    return {str(m.get("id")) for m in (fetch_messages(sid) or []) if m}


def measure_boundary(sid, boundary):
    """Measure the boundary's reality with reversible steps only (stage -> observe -> clear). No commit.

    The hard checks are `session.revert.messageID` and the revert disappearing after clear.
    The message-id diff is reference information (measured on v2.3.2: `message.list` keeps
    returning messages hidden by the stage, so the expected diff is zero and the diff cannot
    verify hiding).
    """
    pre = message_ids(sid)
    staged = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
    if staged.get("messageID"):
        print(f"[measurement aborted] a revert is staged at another boundary: {staged.get('messageID')}. Run --clear first.", file=sys.stderr)
        return 2
    api("POST", f"/api/session/{sid}/revert/stage", {"messageID": boundary, "files": False})
    revert = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
    failed = []
    if revert.get("messageID") != boundary:
        failed.append(f"stage verification failed: revert={revert}")
    if revert.get("partID"):
        print(f"[observation] revert.partID = {revert.get('partID')} (should be absent on v2.3.2)", file=sys.stderr)
    print(f"[measure] stage boundary {boundary}")
    print(f"[measure] session.revert = {revert}")
    post = message_ids(sid)
    print(
        f"[reference] message.list id diff: gone {len(pre - post)}, added {len(post - pre)}"
        " (expected 0, 0 on v2.3.2; the list is not the timeline render and also returns hidden items)"
    )
    print(f"[reference] boundary id still in the list: {boundary in post} (expected True on v2.3.2)")
    api("DELETE", f"/api/session/{sid}/revert")
    after = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
    if after.get("messageID"):
        failed.append(f"revert still present after clear: {after}")
    restored_msgs = fetch_messages(sid) or []
    restored = {str(m.get("id")) for m in restored_msgs if m}
    gone = pre - restored
    added = restored - pre
    if gone:
        failed.append(f"messages disappeared after clear: {len(gone)}")
    # Measured on v2.3.2: clear adds one idle run-end marker (ADMIN_TYPES, not part of boundary computation).
    added_types = {str(m.get("type")) for m in restored_msgs if m and str(m.get("id")) in added}
    if added_types - {"idle"}:
        failed.append(f"types added by clear: {sorted(added_types)} (only idle is allowed)")
    if added_types:
        print(f"[reference] clear added {sorted(added_types)} x1 (measured on v2.3.2; admin type, no effect on boundary computation or commit range)")
    for f in failed:
        print(f"[measurement failed] {f}", file=sys.stderr)
    print("[measure] done. No commit was performed.")
    return 2 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="redo only the answered question (staging is the default)")
    ap.add_argument("--session", help="target session ID (required; list with --list)")
    ap.add_argument("--list", action="store_true", help="list sessions")
    ap.add_argument("--clear", action="store_true", help="clear the staged revert")
    ap.add_argument("--apply", action="store_true",
                    help="in work mode: verify the stage and send the instruction (CLI version of /undo-answer-apply; sending commits the stage)")
    ap.add_argument("--mode", choices=("question", "work"), default="work",
                    help="work=only the later work is reverted, the v0.2.0 boundary (default) / question=v0.1.0 boundary (re-send the previous user message; for ground-truth comparison)")
    ap.add_argument("--inspect", action="store_true", help="read-only: print the layout and computed boundary (no changes)")
    ap.add_argument("--print-prompt", action="store_true", help="read-only: print the re-send body per --mode to stdout (work=instruction / question=previous user message; no staging)")
    ap.add_argument("--measure-boundary", action="store_true",
                    help="measure the work-mode boundary reversibly (stage -> observe -> auto clear; no commit)")
    ap.add_argument("--disposable", action="store_true",
                    help="declare the session as disposable (required with --measure-boundary)")
    ap.add_argument("--commit", action="store_true", help="delete from the boundary on (irreversible; --reprompt required)")
    ap.add_argument("--reprompt", action="store_true", help="after commit, re-send the instruction (work mode) or the previous user message (question mode)")
    ap.add_argument("--allow-version-drift", action="store_true",
                    help="run even on a server older than the verified version (newer and unparseable versions run with a warning by default)")
    args = ap.parse_args()

    # Combining read-only flags with mutating flags is refused so a "read" never mutates by accident.
    readonly = args.list or args.inspect or args.print_prompt
    if readonly and (args.clear or args.apply or args.commit or args.measure_boundary):
        raise SystemExit("--list / --inspect / --print-prompt are read-only and cannot be combined with --clear / --apply / --commit / --measure-boundary.")
    if args.clear and (args.apply or args.commit or args.measure_boundary):
        raise SystemExit("--clear only clears; it cannot be combined with --apply / --commit / --measure-boundary.")
    if args.apply and (args.commit or args.measure_boundary):
        raise SystemExit("--apply only sends; it cannot be combined with --commit / --measure-boundary.")
    if args.apply and args.mode != "work":
        raise SystemExit("--apply must be combined with --mode work (the boundary that uses the instruction).")
    if args.disposable and not args.measure_boundary:
        raise SystemExit("--disposable must be combined with --measure-boundary.")

    version_gate(args.allow_version_drift, readonly)

    if args.list:
        for s in api("GET", "/api/session") or []:
            print(f"{s.get('id')}  {s.get('title') or ''}")
        return 0

    if not args.session:
        raise SystemExit("specify --session <id> (list with --list)")
    sid = args.session
    if not SID_RE.match(sid):
        raise SystemExit("invalid --session value (only [A-Za-z0-9_-]+ accepted)")

    messages = fetch_messages(sid)
    if has_pending_question(messages):
        raise SystemExit("an unanswered question is displayed. Answer or cancel it first (staging now would remove the question entirely, and a later send makes that permanent).")
    found = find_latest_question(messages)
    if not found:
        print("No completed question answer was found in this session.")
        return 1
    boundary, boundary_info = select_boundary(messages, found, args.mode)
    outcome = tail_outcome(messages, found["message"])

    if args.inspect:
        print(describe(found["parts"]))
        print(render_inspect_table(messages, found["message"], boundary_info, outcome))
        return 0 if boundary else 1

    if args.print_prompt:
        # Print the body that will actually be re-sent per --mode (review finding M1: it used to
        # always print the work instruction regardless of mode).
        if args.mode == "question":
            body = last_user_text_before(messages, boundary_info["message"])
            if not body.strip():
                print("the previous user message body is empty (there is nothing to re-send).", file=sys.stderr)
                return 2
            print(body)
        else:
            try:
                print(build_instruction(extract_payload(found["parts"])))
            except PayloadTooLarge as e:
                print(f"[refused] {e}", file=sys.stderr)
                return 2
        return 0

    if args.clear:
        api("DELETE", f"/api/session/{sid}/revert")
        after = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
        if after.get("messageID"):
            print(f"[warning] the revert is still present after clearing: {after}", file=sys.stderr)
            return 2
        print("Cleared the staged revert.")
        return 0

    if not boundary:
        reason = boundary_info.get("reason")
        if reason == "no-work":
            print("There is no work message after the answered question, so there is nothing to revert (use --mode question).")
        else:
            print("After the answered question there are only admin messages (idle, system, ...), no work message (use --mode question).")
        return 1

    if args.apply:
        # CLI equivalent of /undo-answer-apply on all three surfaces. It does not read the plugin
        # record (ctx.storage), so the instruction is recomputed from history (same derivation as --print-prompt).
        try:
            instruction = build_instruction(extract_payload(found["parts"]))
        except PayloadTooLarge as e:
            print(f"[refused] {e}", file=sys.stderr)
            return 2
        staged = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
        if staged.get("messageID") and staged.get("messageID") != boundary:
            print(
                f"[refused] staged at a different boundary than computed ({boundary}): {staged.get('messageID')}. "
                "Aborting without replacing it. Run --clear first.",
                file=sys.stderr,
            )
            return 2
        if not staged.get("messageID"):
            # A commit removes the boundary message and everything after from history; a clear
            # leaves the boundary message (measured on v2.3.2).
            # Boundary still present = already cleared, so do not send (same handling as /undo-answer-cancel).
            if any(m and m.get("id") == boundary for m in messages):
                print(
                    "[refused] the stage appears already cleared (the boundary message is still in history). Not sending.",
                    file=sys.stderr,
                )
                return 2
            print("No staged revert (it may already be committed). The boundary message is gone from history, so sending the instruction.")
        try:
            api("POST", f"/api/session/{sid}/prompt", {"text": instruction})
        except ApiError as e:
            print(f"[failed] sending the instruction failed: {e}", file=sys.stderr)
            print("----- body to send manually -----")
            print(instruction)
            print("-------------------------------")
            return 2
        after = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
        if after.get("messageID"):
            print(f"[warning] the revert is still present after sending: {after}", file=sys.stderr)
            return 2
        print("Sent the instruction (the send committed the stage). The same question will be re-presented.")
        return 0

    if args.measure_boundary:
        if not args.disposable:
            print("--measure-boundary requires --disposable (mutating experiments on real sessions are forbidden by policy).", file=sys.stderr)
            return 2
        if args.mode != "work":
            print("--measure-boundary measures the --mode work boundary.", file=sys.stderr)
            return 2
        return measure_boundary(sid, boundary)

    try:
        instruction = build_instruction(extract_payload(found["parts"])) if args.mode == "work" else ""
    except PayloadTooLarge as e:
        print(f"[refused] {e}", file=sys.stderr)
        return 2

    if args.commit:
        if not args.reprompt:
            raise SystemExit("--commit must be combined with --reprompt (a re-send follows the deletion)")
        if args.mode == "work":
            body = instruction
            if not body.strip():
                raise SystemExit("the instruction is empty. Aborting the commit.")
        else:
            body = last_user_text_before(messages, boundary_info["message"])
            if not body.strip():
                raise SystemExit("the previous user message body is empty. Aborting the commit because it cannot be re-sent.")
        # Commit is irreversible, so right before it re-check that no unanswered question appeared
        # after the boundary computation (a pending question inside the range would be permanently deleted).
        fresh = fetch_messages(sid)
        if has_pending_question(fresh):
            raise SystemExit("an unanswered question was detected right before the commit. Aborting the deletion (a stage may remain).")
        # The commit target must always be the boundary this command detected. Committing while a
        # different boundary is staged would delete beyond the verified range, so re-stage and match.
        staged = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
        if staged.get("messageID") != boundary:
            api("POST", f"/api/session/{sid}/revert/stage", {"messageID": boundary, "files": False})
            staged = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
        if staged.get("messageID") != boundary:
            raise SystemExit("failed to stage at the detected boundary. Aborting the commit.")
        api("POST", f"/api/session/{sid}/revert/commit", {"sessionID": sid})
        print("Committed (deleted from the boundary on).")
        # After a commit there is no undo. If the re-send fails, print the body for manual sending.
        try:
            api("POST", f"/api/session/{sid}/prompt", {"text": body})
            if args.mode == "work":
                print("Sent the instruction. The same question will be re-presented in the session (answer it in the GUI).")
            else:
                print("Re-sent the previous message. The question will be re-presented in the session (answer it in the GUI).")
        except ApiError as e:
            print(f"[warning] the re-send prompt failed: {e}", file=sys.stderr)
            print("The tail is already deleted. Send the following (the re-send body) manually in the session:")
            print("-----")
            print(body)
            print("-----")
            return 2
        return 0

    staged_now = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
    if staged_now.get("messageID"):
        raise SystemExit("a revert is staged at another boundary. Clear it first with --clear (or /undo-answer-cancel in the GUI).")
    try:
        api("POST", f"/api/session/{sid}/revert/stage", {"messageID": boundary, "files": False})
    except ApiError as e:
        # Staging a running session surfaces as HTTP 409 (measured on v2.3.2). The GUI side sees SessionBusy.
        text = (e.stderr or "") + (e.stdout or "")
        if "SessionBusy" in text or "409 Conflict" in text:
            print("The session is running. Press Esc in the GUI to interrupt, then run this again (this tool never interrupts automatically).", file=sys.stderr)
            return 2
        raise

    staged = (api("GET", f"/api/session/{sid}") or {}).get("revert") or {}
    if staged.get("messageID") != boundary:
        print(f"[warning] could not confirm the stage (revert={staged})", file=sys.stderr)
        return 2
    print(describe_boundary(boundary_info, outcome))
    if args.mode == "work":
        print("Staged. To re-present: `python tools/smoke.py --session <sid> --mode work --apply`, "
              "or /undo-answer-apply in the session (all three surfaces). To only fetch the instruction: --print-prompt (read-only).")
    else:
        print("Staged. The previous user message can be inspected with `--inspect`. Sending anything commits the stage.")
    print("Note: sending a new message while staged commits the stage and the hidden tail becomes unrecoverable. Clear with --clear (/undo-answer-cancel).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
