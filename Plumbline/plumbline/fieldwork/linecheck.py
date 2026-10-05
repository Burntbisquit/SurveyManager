"""Linework, read whole: the issues one description cannot show, and the tools for them.

Every other check in this program reads **one point at a time**.  A line is not a point: ``TOC PC``
on OID 46 is a perfectly good description whose *meaning* is wrong, and the only place that shows
is the line it belongs to - a segment that starts, runs, and stops without an ``END``; a curve that
starts and never ends.  Worse, the two ends of one mistake usually sit on **two different points**,
which is why the tool that fixes them has to be allowed to clear a second flag it was not aimed at.

The vocabulary is the field book's, and the order is the whole game::

    ST  (start line)  →  PC  (start curve)  →  PT  (end curve)  →  END / X  (end line, close)

so ``TOC PC PT END`` is right, ``TOC PT PC END`` is not, and ``TOC PC PT`` never finished.  A fix
that appends the missing word to the end of the description can therefore produce a description
that is still wrong - which is exactly why every fix here is **proposed, then validated**: the
proposal is offered, and after it is applied the line is read again, because the only honest
answer to "did that help?" is to look.

This module is Qt-free on purpose: the field window's Line Repair tab and the drawing window's
Check Fieldwork dock both use it, and neither should be able to disagree with the other about
where a line ends.
"""
from __future__ import annotations

from . import config as C

#: The four ways a line can be incomplete.  The strings are what a user reads and what the
#: Line Repair filter offers; they are also what lands in a ``.fwc`` row's IssueType.
ISSUE_TYPES = ("Missing ST", "Missing END", "Missing PC", "Missing PT")

#: ...and the short token each one travels as, because a tool switches on a flag, not on prose.
ISSUE_FLAGS = {
    "Missing ST": "MissingStart",
    "Missing END": "MissingEnd",
    "Missing PC": "MissingPC",
    "Missing PT": "MissingPT",
}

#: Outside in.  ST starts the line, PC starts the curve inside it, PT ends that curve, and only
#: then may the line end (END) or close (X) - the field book's own hierarchy, kept here so a
#: proposal can be *placed* rather than appended.
RANK = {"st": 0, "pc": 1, "pt": 2, "end": 3, "x": 3}


def _command_set(command_set=None) -> set:
    return {str(c).strip().casefold() for c in (command_set if command_set is not None else C.COMMAND_SET)}


def _f2f_for(fieldbook_path, f2f_set):
    """The code vocabulary: the caller's if it has one, else the field book's, else none.

    None rather than an empty set matters downstream: with no vocabulary every code reads as
    unknown, and an unknown code has no line commands, so the check would answer "no issues" -
    the one answer that is certainly wrong.  Callers are expected to say which of the two they
    did, and this function does not pretend otherwise.
    """
    if f2f_set:
        return f2f_set
    if fieldbook_path:
        try:
            from .parse import build_f2f_set_from_fieldbook
            return build_f2f_set_from_fieldbook(fieldbook_path)
        except Exception:
            return set()
    return set()


def _command_set_for(fieldbook_path, command_set):
    if command_set is not None:
        return command_set
    if fieldbook_path:
        try:
            from .config import get_command_set
            return get_command_set(fieldbook_path)
        except Exception:
            return None
    return None


# --------------------------------------------------------------------------------- detection
def detect_line_errors(working_rows, fieldbook_path=None, f2f_set=None, command_set=None,
                       rules=None) -> list[dict]:
    """Every line in the file, read as a whole, and what is wrong with it.

    Working rows are the 8-column list (OID, Pt#, N, E, Z, Desc, Parent, Source) in **file
    order** - a line is the order the crew shot it, so a sorted list is a different answer.

    Returns one dict per issue::

        {"gid", "issue_type", "oid", "line_id", "detail", "fix_suggestion", "seg_id", "proposal"}

    ``oid`` is the point the issue is *about* (where the fix belongs), ``line_id`` the code
    token it was grouped under, and ``proposal`` the description that would fix it - empty
    when there is no safe guess, in which case the user keys it in (see
    :func:`propose_fix`).
    """
    if not working_rows:
        return []
    from .parse import parse_desc_field

    f2f = _f2f_for(fieldbook_path, f2f_set)
    cs = _command_set_for(fieldbook_path, command_set)

    oid_list = []
    for wr in working_rows:
        oid = str(wr[0]).strip() if len(wr) > 0 else ""
        raw = str(wr[5]).strip() if len(wr) > 5 else ""
        oid_list.append((oid, raw, wr))
    try:
        oid_list.sort(key=lambda x: int(x[0]) if x[0].isdigit() else x[0])
    except Exception:
        pass

    # Group every point under the code token that owns its line commands.  A code with no
    # commands anywhere is not a line at all and is skipped below - the description check's
    # business, not this one's.
    segments_by_line: dict[str, list] = {}
    raw_by_line: dict[str, str] = {}
    for oid, raw, _wr in oid_list:
        parsed = parse_desc_field(raw, f2f, fieldbook_path=fieldbook_path, command_set=cs, rules=rules)
        classified = parsed.get("code_classified", [])
        cmds_by_code: dict[str, list] = {}
        for i, item in enumerate(classified):
            if item["type"] == "command" and item.get("status") == "valid" and "attached_to" in item:
                cidx = item["attached_to"]
                code_item = classified[cidx] if 0 <= cidx < len(classified) else None
                if code_item and code_item["type"] == "code":
                    line_id = code_item["raw"].strip().casefold()
                    cmds_by_code.setdefault(line_id, []).append(item["norm"].casefold())
                    raw_by_line[line_id] = code_item["raw"]
            elif item["type"] == "code" and item["status"] in ("exact", "line_instance"):
                line_id = item["raw"].strip().casefold()
                cmds_by_code.setdefault(line_id, [])
                raw_by_line.setdefault(line_id, item["raw"])
        for line_id, cmds in cmds_by_code.items():
            segments_by_line.setdefault(line_id, []).append((oid, cmds, raw, raw_by_line.get(line_id, line_id)))

    errors: list[dict] = []

    def raw_of(oid):
        for o, raw, _wr in oid_list:
            if o == str(oid):
                return raw
        return ""

    def issues_for(line_id, pts):
        """One code's points, read as a sequence of segments."""
        out: list[dict] = []
        segments: list[list] = []
        cur_seg: list = []
        in_line = False
        code_raw = pts[0][3] if pts else line_id

        def add(issue_type, oid, detail, suggestion):
            out.append({
                "issue_type": issue_type, "oid": oid, "line_id": line_id,
                "detail": detail, "fix_suggestion": suggestion, "seg_id": len(segments) + 1,
                "proposal": propose_fix(issue_type, raw_of(oid), line_id, command_set=cs),
            })

        for oid, cmds, raw, _code in pts:
            if "st" in cmds:
                if in_line and cur_seg:
                    add("Missing END", cur_seg[-1][0],
                        f"Line {code_raw} segment missing END/X before new ST at OID {oid} ({raw}) "
                        f"- previous segment started at OID {cur_seg[0][0]}",
                        f"Add END to OID {cur_seg[-1][0]}")
                    segments.append(cur_seg)
                    cur_seg = []
                in_line = True
                cur_seg.append((oid, cmds, raw))
            elif in_line:
                cur_seg.append((oid, cmds, raw))
                if "end" in cmds or "x" in cmds:
                    segments.append(cur_seg)
                    cur_seg = []
                    in_line = False
            elif cmds:
                # Commands on a code with no ST anywhere before them: the segment never started.
                add("Missing ST", oid,
                    f"Line {code_raw} has {cmds} at OID {oid} ({raw}) without a prior ST - "
                    f"every segment needs a START",
                    f"Add ST to OID {oid}")
                in_line = True
                cur_seg = [(oid, cmds, raw)]
                if "end" in cmds or "x" in cmds:
                    segments.append(cur_seg)
                    cur_seg = []
                    in_line = False
        if cur_seg:
            add("Missing END", cur_seg[-1][0],
                f"Line {code_raw} segment starting at OID {cur_seg[0][0]} never closed with END/X "
                f"(last point OID {cur_seg[-1][0]})",
                f"Add END/X to OID {cur_seg[-1][0]}")
            segments.append(cur_seg)
            cur_seg = []

        for seg in segments:
            pcs = [oid for oid, cmds, _raw in seg if "pc" in cmds]
            pts_ = [oid for oid, cmds, _raw in seg if "pt" in cmds]
            if pcs and not pts_:
                add("Missing PT", pcs[0],
                    f"Line {code_raw} has PC at OID {pcs[0]} without a matching PT before the end",
                    f"Add PT to OID {pcs[0]} (after PC, before END/X)")
            if pts_ and not pcs:
                add("Missing PC", pts_[0],
                    f"Line {code_raw} has PT at OID {pts_[0]} without a prior PC",
                    f"Add PC to OID {pts_[0]} (before PT)")
        return out

    for line_id, pts in segments_by_line.items():
        has_line_cmd = any(any(c in ("st", "pc", "pt", "end", "x") for c in cmds) for _, cmds, _, _ in pts)
        if not has_line_cmd:
            continue
        for issue in issues_for(line_id, pts):
            issue["gid"] = str(len(errors) + 1)
            errors.append(issue)
    return errors


# --------------------------------------------------------------------------------- the tools
def propose_fix(issue_type: str, current_desc: str, line_id: str = "", command_set=None) -> str:
    """The description that would fix *issue_type* on a point that reads *current_desc*.

    Empty string means **no safe guess**: the caller offers Key-In instead of pretending.

    The word is *placed*, not appended - appended guesses are the ones that fail validation
    (``TOC PC PT`` + ``END`` on the end of a ``PT``-less curve reads fine and is still wrong).
    A description holding more than one code (a multicode ``TOC ST - EC ST``) gets no proposal
    at all: the token to edit is a judgement, and a judgement belongs to the user.
    """
    words = (current_desc or "").split()
    if not words:
        return ""
    cs = _command_set(command_set)
    if words[0].casefold() in cs:                       # a description starting with a command
        return ""
    codes = [w for w in words if w.casefold() not in cs and w not in ("-", "/")]
    if len(codes) != 1:                                  # multicode - key it in by hand
        return ""
    head, rest = words[0], words[1:]
    lo = [w.casefold() for w in rest]
    line = (line_id or "").casefold().strip()
    if line and line != head.casefold() and head.casefold().rstrip("0123456789") != line:
        # The issue is grouped under a different code token than this description starts with.
        return ""

    def insert_before(names, word):
        for i, tok in enumerate(lo):
            if tok in names:
                return " ".join([head, *rest[:i], word, *rest[i:]])
        return " ".join([head, *rest, word])

    if issue_type == "Missing ST":
        if "st" in lo:
            return ""
        return " ".join([head, "ST", *rest])             # ST ranks outside every other command
    if issue_type == "Missing END":
        if "end" in lo or "x" in lo:
            return ""
        return " ".join([head, *rest, "END"])            # the line ends last, so it goes last
    if issue_type == "Missing PC":
        if "pc" in lo:
            return ""
        return insert_before(("pt", "end", "x"), "PC")   # inside the line, before what it feeds
    if issue_type == "Missing PT":
        if "pt" in lo:
            return ""
        return insert_before(("end", "x"), "PT")         # the curve ends before the line does
    return ""


def validate_fix(working_rows, oid, new_desc, fieldbook_path=None, f2f_set=None, command_set=None,
                 rules=None) -> dict:
    """Apply *new_desc* to *oid* **in memory**, read the lines again, and say what it cleared.

    The field book's own note asked for this ("after full rewrite, re-run ... and show a toast
    'also cleared LineOrderError on OID 46'"): fixing the end of one line routinely fixes the
    start of another, and a tool that only reports its own row makes the second one look like
    work still to do.

    Returns ``{"ok", "cleared", "also_cleared", "still", "note"}``; nothing is written.
    """
    cs = _command_set_for(fieldbook_path, command_set)
    before = detect_line_errors(working_rows, fieldbook_path=fieldbook_path, f2f_set=f2f_set,
                                command_set=cs, rules=rules)
    rows2 = []
    found = False
    for r in working_rows:
        row = list(r)
        if str(row[0]).strip() == str(oid).strip():
            if len(row) > 5:
                row[5] = new_desc
            found = True
        rows2.append(row)
    if not found:
        return {"ok": False, "cleared": [], "also_cleared": [], "still": [],
                "note": f"There is no point with OID {oid} in the working file - nothing was changed."}
    after = detect_line_errors(rows2, fieldbook_path=fieldbook_path, f2f_set=f2f_set,
                               command_set=cs, rules=rules)
    key = lambda e: (str(e["issue_type"]), str(e["oid"]), str(e.get("line_id", "")))  # noqa: E731
    seen_after = {key(e) for e in after}
    cleared = [e for e in before if key(e) not in seen_after and str(e["oid"]).strip() == str(oid).strip()]
    also = [e for e in before if key(e) not in seen_after and str(e["oid"]).strip() != str(oid).strip()]
    still = [e for e in after if str(e["oid"]).strip() == str(oid).strip()]
    return {"ok": not still, "cleared": cleared, "also_cleared": also, "still": still,
            "note": fix_note(oid, new_desc, cleared, also, still)}


def fix_note(oid, new_desc, cleared, also, still) -> str:
    """One sentence a status line can carry: what the fix did, and what it left."""
    bits = []
    if cleared:
        bits.append(f"cleared {', '.join(e['issue_type'] for e in cleared)} at OID {oid}")
    if also:
        bits.append("also cleared " + ", ".join(f"{e['issue_type']} at OID {e['oid']}" for e in also))
    if still:
        bits.append(f"OID {oid} still has " + ", ".join(e["issue_type"] for e in still)
                    + f" after '{new_desc}' - write it by hand (Key-In)")
    if not bits:
        return f"'{new_desc}' applied. No line issue was flagged at OID {oid}, before or after."
    return f"'{new_desc}' applied - " + "; ".join(bits) + "."


# --------------------------------------------------------------------------------- the report
def report_rows(issues, statuses=None, start_gid: int = 1) -> list:
    """``.fwc`` rows (DisplayTab=Line) for a list of issues - one row per issue, OID-minimal.

    *statuses* is keyed by ``(issue_type, oid)`` and carries the decisions a user has already
    made about these issues, so a re-run does not quietly resurrect an Ignored one.  See
    :func:`statuses_from_rows` for the other half of that round trip.
    """
    statuses = statuses or {}
    rows = []
    gid = start_gid
    for e in issues:
        issue = str(e.get("issue_type", ""))
        oid = str(e.get("oid", ""))
        decided = statuses.get((issue, oid)) or statuses.get((issue, str(oid))) or {}
        rows.append([
            str(gid), "Line", issue, oid,
            ISSUE_FLAGS.get(issue, ""),
            str(e.get("detail", "")),
            str(e.get("fix_suggestion", "")),
            str(decided.get("status") or "Open"),
            str(decided.get("comments") or ""),
        ])
        gid += 1
    return rows


def statuses_from_rows(rows) -> dict:
    """The decisions stored in a ``.fwc``'s Line rows: ``{(issue_type, oid): {status, comments}}``.

    Only rows that actually decided something are returned - an Open row with no comment is
    the absence of a decision, not a decision.
    """
    out = {}
    for r in rows or []:
        try:
            display, issue, oid, status, comments = r[1], r[2], r[3], r[7], r[8]
        except IndexError:
            continue
        if str(display).strip().lower() != "line":
            continue
        if str(status).strip().lower() in ("", "open") and not str(comments).strip():
            continue
        out[(str(issue).strip(), str(oid).strip())] = {"status": str(status).strip(),
                                                       "comments": str(comments).strip()}
    return out


__all__ = ["ISSUE_TYPES", "ISSUE_FLAGS", "RANK", "detect_line_errors", "propose_fix",
           "validate_fix", "fix_note", "report_rows", "statuses_from_rows"]
