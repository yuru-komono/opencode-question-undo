r"""Drift check between the two implementations (server plugin `src/undo-kernel.js` <-> CLI `tools/undo_core.py`).

The server plugin part and the CLI intentionally implement the same procedure twice (the CLI is
also the measurement harness and fallback). The instruction sent to the model and the gate
values that build it must agree on both sides, so a machine gate guards them.

Checks:
1. The string literals (in line order) between `// INSTR-BEGIN` and `// INSTR-END` in
   `src/undo-kernel.js` match `undo_core.INSTRUCTION_FRAME` line by line.
2. The two payload-block sentinels are the same strings on both sides.
3. The payload field-label vocabulary (question / header / multiple / options / label /
   description) appears in both sources.
4. The four payload cap values agree (cap drift would silently change what is refused).
5. The runtime value of `ZERO_WIDTH_SPACE` matches (the JS side is decoded from its escape
   notation. Past measured drift: a double-escaped `"\\u200b"` left 6 characters of garbage).
6. The payload-block structural strings (field line heads with indentation) are the same on both sides.
7. The version pin agrees in 3 places (`src/undo-server.js`, `tools/smoke.py`, and the
   `engines` field of `package.json`) so the version gate cannot be looser in one place.
8. The `ADMIN_TYPES` set agrees (read from the JS `new Set([...])` literal and the Python
   runtime value. This hand-mirrored admin-type set silently shifts boundary computation if it drifts).
9. The boundary rule-name vocabulary (`raw-successor` / `skip-idle-to-first-work` / `no-work` /
   `admin-only` / `questionStep`) appears on both sides (JS: kernel+server, Python: undo_core+smoke).
10. The `SID_RE` pattern strings agree (the session-id gate before URL interpolation; the only
    regex whose drift silently widens the attack surface).
11. The `VERSION_RE` pattern strings agree (the version-gate parse rule; same regex-literal
    idiom as #10. The Python side carries a `(?a)` prefix for engine semantics parity and it
    is stripped before comparison; a missing prefix is itself a finding).
12. The version verdict tokens (`same` / `newer` / `older` / `unknown`) appear as quoted
    literals inside the comparator bodies, and each gate calls its comparator by name (a
    whole-file substring check would pass after a rename because comments carry the vocabulary).

Usage:
    python tools/check_instruction_parity.py
exit code: 0=agree / 1=drift detected or precondition unresolvable / 2=argparse usage error
"""

import json
import re
import sys
from pathlib import Path

import undo_core
from undo_core import INSTRUCTION_FRAME, SENTINEL_BEGIN, SENTINEL_END

BEGIN_MARK = "// INSTR-BEGIN"
END_MARK = "// INSTR-END"
LITERAL_RE = re.compile(r"\"((?:[^\"\\]|\\.)*)\"")
FIELD_LABELS = ("question:", "header:", "multiple:", "options:", "label:", "description:")
CAP_NAMES = ("MAX_QUESTIONS_PER_PART", "MAX_OPTIONS_PER_QUESTION", "MAX_STRING_CHARS", "MAX_INSTRUCTION_CHARS")
# Payload-block structural strings (JS literals vs Python f-string prefixes).
STRUCT_STRINGS = ("tool: question", "  questions:", "    options:")
ROOT = Path(__file__).resolve().parent.parent
JS_FILE = ROOT / "src" / "undo-kernel.js"
SERVER_JS = ROOT / "src" / "undo-server.js"
SMOKE_PY = ROOT / "tools" / "smoke.py"
UNDO_CORE_PY = ROOT / "tools" / "undo_core.py"
PKG_JSON = ROOT / "package.json"

# Boundary rule-name vocabulary (JS side: kernel+server, Python side: undo_core+smoke).
RULE_NAMES = ("raw-successor", "skip-idle-to-first-work", "no-work", "admin-only", "questionStep")
# Version verdict vocabulary (the four tokens returned by compareVersions / compare_versions).
VERDICT_NAMES = ("same", "newer", "older", "unknown")
QUOTED_RE = re.compile(r"\"([^\"]+)\"")


def js_frame(text):
    """String literals between the INSTR-BEGIN / INSTR-END lines, in line order (line match; words inside lines are not used)."""
    lines = text.split("\n")
    try:
        begin = next(i for i, ln in enumerate(lines) if ln.strip() == BEGIN_MARK)
        end = next(i for i, ln in enumerate(lines) if ln.strip() == END_MARK)
    except StopIteration:
        return None
    frame = []
    for ln in lines[begin + 1 : end]:
        for raw in LITERAL_RE.findall(ln):
            frame.append(decode_literal(f'"{raw}"'))
    return frame


def decode_literal(literal):
    """Decode a JS string literal (with quotes) into a Python string (resolves \\u200b etc.)."""
    try:
        return json.loads(literal)
    except ValueError:
        return literal


def js_string_const(text, name):
    """Runtime value of `const <NAME> = "...";`, or None if not found."""
    m = re.search(rf"(?:const|export const)\s+{name}\s*=\s*\"((?:[^\"\\]|\\.)*)\"", text)
    if not m:
        return None
    return decode_literal(f'"{m.group(1)}"')


def js_int_const(text, name):
    """Integer value of `export const <NAME> = 12;`, or None if not found."""
    m = re.search(rf"(?:const|export const)\s+{name}\s*=\s*(\d+)\s*;", text)
    if not m:
        return None
    return int(m.group(1))


def pinned_versions():
    """Read the version pin from 3 places (server part, CLI, engines). Unreadable places are None."""
    out = {}
    for label, file, pattern in (
        ("src/undo-server.js", SERVER_JS, r'const PINNED_VERSION = "([^"]+)"'),
        ("tools/smoke.py", SMOKE_PY, r'^PINNED_VERSION = "([^"]+)"'),
    ):
        try:
            m = re.search(pattern, file.read_text(encoding="utf-8"), re.MULTILINE)
            out[label] = m.group(1) if m else None
        except OSError:
            out[label] = None
    try:
        out["package.json"] = (json.loads(PKG_JSON.read_text(encoding="utf-8")).get("engines") or {}).get("opencode")
    except (OSError, ValueError):
        out["package.json"] = None
    return out


def js_admin_types(text):
    """Word set of the JS `export const ADMIN_TYPES = new Set([...])` literal, or None if unreadable."""
    m = re.search(r"export const ADMIN_TYPES = new Set\(\[(.*?)\]\)", text, re.DOTALL)
    if not m:
        return None
    return set(QUOTED_RE.findall(m.group(1)))


def sid_re_patterns():
    """SID_RE pattern strings from both the JS and Python sides. Unreadable sides are None."""
    out = {}
    try:
        m = re.search(r"const SID_RE = /(.+?)/;", (ROOT / "src" / "undo-server.js").read_text(encoding="utf-8"))
        out["src/undo-server.js"] = m.group(1) if m else None
    except OSError:
        out["src/undo-server.js"] = None
    try:
        m = re.search(r'SID_RE = re\.compile\(r"([^"]+)"\)', SMOKE_PY.read_text(encoding="utf-8"))
        out["tools/smoke.py"] = m.group(1) if m else None
    except OSError:
        out["tools/smoke.py"] = None
    return out


def version_re_patterns():
    """VERSION_RE pattern strings from both the JS and Python sides. Unreadable sides are None.
    The Python side is expected to carry the `(?a)` prefix (engine parity; handled by the caller)."""
    out = {}
    try:
        m = re.search(r"const VERSION_RE = /(.+?)/;", JS_FILE.read_text(encoding="utf-8"))
        out["src/undo-kernel.js"] = m.group(1) if m else None
    except OSError:
        out["src/undo-kernel.js"] = None
    try:
        m = re.search(r'VERSION_RE = re\.compile\(r"([^"]+)"\)', UNDO_CORE_PY.read_text(encoding="utf-8"))
        out["tools/undo_core.py"] = m.group(1) if m else None
    except OSError:
        out["tools/undo_core.py"] = None
    return out


def comparator_bodies():
    """Function bodies of the comparator pair (for the scoped verdict-token check). Unreadable sides are None."""
    out = {}
    try:
        m = re.search(r"export function compareVersions\(found, pinned\) \{(.*?)\n\}",
                      JS_FILE.read_text(encoding="utf-8"), re.DOTALL)
        out["src/undo-kernel.js"] = m.group(1) if m else None
    except OSError:
        out["src/undo-kernel.js"] = None
    try:
        m = re.search(r"def compare_versions\(found, pinned\):\n(.*?)(?=\n\ndef |\Z)",
                      UNDO_CORE_PY.read_text(encoding="utf-8"), re.DOTALL)
        out["tools/undo_core.py"] = m.group(1) if m else None
    except OSError:
        out["tools/undo_core.py"] = None
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    findings = []
    try:
        js_text = JS_FILE.read_text(encoding="utf-8")
    except OSError as e:
        print(f"parity: read failure {JS_FILE}: {e}", file=sys.stderr)
        return 1

    js = js_frame(js_text)
    if js is None:
        print("parity: INSTR-BEGIN / INSTR-END markers not found in the JS side", file=sys.stderr)
        return 1

    if len(js) != len(INSTRUCTION_FRAME):
        findings.append(f"line count differs: JS {len(js)} / Python {len(INSTRUCTION_FRAME)}")
    for i in range(min(len(js), len(INSTRUCTION_FRAME))):
        if js[i] != INSTRUCTION_FRAME[i]:
            findings.append(f"line {i + 1} differs\n  JS : {js[i]}\n  PY : {INSTRUCTION_FRAME[i]}")

    for token in (SENTINEL_BEGIN, SENTINEL_END):
        if token not in js_text:
            findings.append(f"sentinel missing in the JS side: {token}")

    for label in FIELD_LABELS:
        if label not in js_text:
            findings.append(f"field label missing in the JS side: {label}")

    for name in CAP_NAMES:
        js_val = js_int_const(js_text, name)
        py_val = getattr(undo_core, name, None)
        if js_val is None:
            findings.append(f"cap constant missing in the JS side: {name}")
        elif js_val != py_val:
            findings.append(f"cap value differs {name}: JS {js_val} / Python {py_val}")

    js_zwsp = js_string_const(js_text, "ZERO_WIDTH_SPACE")
    if js_zwsp is None:
        findings.append("ZERO_WIDTH_SPACE missing in the JS side")
    elif js_zwsp != undo_core.ZERO_WIDTH_SPACE:
        findings.append(
            f"ZERO_WIDTH_SPACE differs: JS {json.dumps(js_zwsp)} (len {len(js_zwsp)}) / "
            f"Python {json.dumps(undo_core.ZERO_WIDTH_SPACE)} (len {len(undo_core.ZERO_WIDTH_SPACE)})"
        )

    for struct in STRUCT_STRINGS:
        if f'"{struct}"' not in js_text:
            findings.append(f"payload structural string missing in the JS side: {struct!r}")

    pins = pinned_versions()
    for label, value in pins.items():
        if value is None:
            findings.append(f"version pin unreadable: {label}")
        elif not re.fullmatch(r"[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}", value):
            # A pin outside the comparator's own parse rule (1-9 ASCII digits per segment)
            # would return unknown and silently disable the older-version refusal (#7's purpose).
            findings.append(f"version pin is not plain x.y.z: {label}={value!r}")
    if all(v is not None for v in pins.values()) and len(set(pins.values())) > 1:
        findings.append("version pins differ: " + " / ".join(f"{k}={v}" for k, v in pins.items()))

    # 8. ADMIN_TYPES set (JS literal vs Python runtime value).
    js_admin = js_admin_types(js_text)
    if js_admin is None:
        findings.append("no ADMIN_TYPES new Set literal found in the JS side")
    elif js_admin != set(undo_core.ADMIN_TYPES):
        findings.append("ADMIN_TYPES differs: " + " / ".join(sorted(js_admin.symmetric_difference(undo_core.ADMIN_TYPES))))

    # 9. Boundary rule-name vocabulary (JS: kernel+server, Python: undo_core+smoke).
    try:
        py_core_text = UNDO_CORE_PY.read_text(encoding="utf-8")
        py_smoke_text = SMOKE_PY.read_text(encoding="utf-8")
        js_server_text = SERVER_JS.read_text(encoding="utf-8")
    except OSError as e:
        findings.append(f"rule-name check read failure: {e}")
        py_core_text = py_smoke_text = js_server_text = ""
    js_side_text = js_text + js_server_text
    py_side_text = py_core_text + py_smoke_text
    for name in RULE_NAMES:
        if name not in js_side_text:
            findings.append(f"boundary rule name missing in the JS side: {name}")
        if name not in py_side_text:
            findings.append(f"boundary rule name missing in the Python side: {name}")

    # 10. SID_RE pattern strings.
    sids = sid_re_patterns()
    for label, value in sids.items():
        if value is None:
            findings.append(f"SID_RE unreadable: {label}")
    if all(v is not None for v in sids.values()) and len(set(sids.values())) > 1:
        findings.append("SID_RE patterns differ: " + " / ".join(f"{k}={v!r}" for k, v in sids.items()))

    # 11. VERSION_RE pattern strings (the version-gate parse rule; same idiom as #10). The
    #     Python `(?a)` prefix is engine-parity normalization for \d and $; strip before compare.
    vers = version_re_patterns()
    for label, value in vers.items():
        if value is None:
            findings.append(f"VERSION_RE unreadable: {label}")
    py_re = vers.get("tools/undo_core.py")
    if py_re is not None:
        if py_re.startswith("(?a)"):
            vers["tools/undo_core.py"] = py_re[len("(?a)"):]
        else:
            findings.append("Python VERSION_RE lacks the (?a) prefix (engine parity for \\d and $)")
    if all(v is not None for v in vers.values()) and len(set(vers.values())) > 1:
        findings.append("VERSION_RE patterns differ: " + " / ".join(f"{k}={v!r}" for k, v in vers.items()))

    # 12. Version verdict tokens, scoped to the comparator bodies (a whole-file substring check
    #     would pass after a rename because comments carry the vocabulary). Each gate must also
    #     call its comparator by name.
    bodies = comparator_bodies()
    for label, body in bodies.items():
        if body is None:
            findings.append(f"comparator body unreadable: {label}")
            continue
        for name in VERDICT_NAMES:
            if f'"{name}"' not in body:
                findings.append(f"verdict literal missing in comparator body: {label} {name}")
    for label, needle, text in (
        ("src/undo-server.js", "compareVersions(", js_server_text),
        ("tools/smoke.py", "compare_versions(", py_smoke_text),
    ):
        if needle not in text:
            findings.append(f"gate does not call the comparator: {label}")

    if findings:
        for f in findings:
            print(f"parity: {f}", file=sys.stderr)
        print(f"parity: {len(findings)} drift finding(s) (make src/undo-kernel.js and tools/undo_core.py agree)", file=sys.stderr)
        return 1

    print(
        f"parity: OK (instruction {len(INSTRUCTION_FRAME)} lines, 2 sentinels, {len(FIELD_LABELS)} field labels, "
        f"{len(CAP_NAMES)} caps, ZWSP match, {len(STRUCT_STRINGS)} structural strings, version pin {pins.get('tools/smoke.py')} (plain x.y.z), "
        f"{len(undo_core.ADMIN_TYPES)} ADMIN_TYPES words, {len(RULE_NAMES)} rule names, SID_RE match, "
        f"VERSION_RE match, {len(VERDICT_NAMES)} verdict tokens)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
