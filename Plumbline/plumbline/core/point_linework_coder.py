"""Point recoding engine for field-to-finish linework.

In survey field-to-finish workflows (Carlson, Civil 3D, Leica Infinity, Trimble Business Center),
linework is driven entirely by point descriptions and coding conventions:
    EP1 ST        -> Starts edge of pavement string 1
    EP1           -> Intermediate vertex on string 1
    EP1 PC        -> Point of curvature on string 1
    EP1 PT        -> Point of tangency on string 1
    EP1 END       -> Terminates string 1
    EP1 CLS       -> Closes string 1 back to its start point
    EP1 / TOC1 ST -> Multicode on single point

When linework is edited, edited on canvas, or repaired in QA, this engine modifies the underlying
`SurveyPoint.desc` on the points themselves so that:
1. Re-running `project.process_linework()` produces the identical linework.
2. Exporting points (PNEZD CSV, LandXML, DXF) to outside software preserves the linework structure.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Sequence

from .featurecodes import (BEGIN_FLAGS, CLOSE_FLAGS, END_FLAGS, parse_description)

if TYPE_CHECKING:
    from .model import SurveyPoint
    from .project import Project


def update_point_token(desc: str, old_code_prefix: str, new_token: str) -> str:
    """Replace an existing code prefix in a description, respecting multicodes separated by '/'.

    If old_code_prefix is not found, prepends or appends new_token.
    """
    if not desc:
        return new_token
    # Split multicodes if separated by '/'
    parts = [p.strip() for p in desc.split("/") if p.strip()]
    if not parts:
        return new_token

    replaced = False
    new_parts = []
    old_upper = old_code_prefix.upper()
    for part in parts:
        tokens = part.split()
        if tokens and (tokens[0].upper() == old_upper or tokens[0].upper().startswith(old_upper)):
            # Replace code in this multicode part
            new_parts.append(new_token)
            replaced = True
        else:
            new_parts.append(part)

    if not replaced:
        new_parts.append(new_token)

    return " / ".join(new_parts)


def remove_point_token(desc: str, code_prefix: str) -> str:
    """Remove a line code token from a point description."""
    if not desc:
        return ""
    parts = [p.strip() for p in desc.split("/") if p.strip()]
    old_upper = code_prefix.upper()
    remaining = []
    for part in parts:
        tokens = part.split()
        if tokens and (tokens[0].upper() == old_upper or tokens[0].upper().startswith(old_upper)):
            continue
        remaining.append(part)
    return " / ".join(remaining)


def join_points_to_string(points: Sequence[SurveyPoint], code: str,
                          string_id: str = "", closed: bool = False,
                          start_flag: str = "ST", end_flag: str = "END") -> list[SurveyPoint]:
    """Recode a sequence of points to form a linework string.

    Point 0 gets '{code}{string_id} {start_flag}'
    Intermediate points get '{code}{string_id}'
    Last point gets '{code}{string_id} CLS' (if closed) or '{code}{string_id} {end_flag}'
    """
    if not points:
        return []

    code_clean = (code or "EP").strip().upper()
    str_clean = str(string_id).strip()
    prefix = f"{code_clean}{str_clean}".strip()

    n = len(points)
    modified = []

    for i, p in enumerate(points):
        if n == 1:
            token = prefix
        elif i == 0:
            token = f"{prefix} {start_flag}".strip()
        elif i == n - 1:
            closing_flag = "CLS" if closed else end_flag
            token = f"{prefix} {closing_flag}".strip()
        else:
            token = prefix

        # Update point description
        orig_desc = p.desc or ""
        tokens = orig_desc.split()
        old_prefix = tokens[0] if tokens else ""

        # Check if point already has matching code prefix
        if old_prefix and old_prefix.upper().startswith(code_clean):
            p.desc = update_point_token(orig_desc, old_prefix, token)
        elif not orig_desc:
            p.desc = token
        else:
            p.desc = f"{token} / {orig_desc}" if "/" not in orig_desc else update_point_token(orig_desc, "", token)

        modified.append(p)

    return modified


def reverse_string_coding(points: Sequence[SurveyPoint], code_prefix: str = "") -> list[SurveyPoint]:
    """Reverse the linework direction of a sequence of points.

    Swaps the Start and End flags between first and last points, and reverses point order.
    """
    if len(points) < 2:
        return list(points)

    pts = list(points)
    p_first = pts[0]
    p_last = pts[-1]

    # Extract existing code prefix
    if not code_prefix:
        tokens = (p_first.desc or "").split()
        code_prefix = tokens[0] if tokens else "EP"

    # Clean old flags from first and last
    desc_first_clean = re.sub(r"\b(ST|START|B|BEG|BEGIN)\b", "", p_first.desc or "", flags=re.IGNORECASE).strip()
    desc_last_clean = re.sub(r"\b(END|E|ED|CLS|CLOSE|C)\b", "", p_last.desc or "", flags=re.IGNORECASE).strip()

    # Determine if previously closed
    was_closed = any(f in (p_last.desc or "").upper().split() for f in CLOSE_FLAGS)

    # First point becomes last point with END or CLS
    p_first.desc = f"{desc_first_clean} {'CLS' if was_closed else 'END'}".strip()

    # Last point becomes first point with ST
    p_last.desc = f"{desc_last_clean} ST".strip()

    # Normalize double spaces
    p_first.desc = re.sub(r"\s+", " ", p_first.desc)
    p_last.desc = re.sub(r"\s+", " ", p_last.desc)

    # For intermediate points, swap curve start/end (PC <-> PT)
    for p in pts[1:-1]:
        d = p.desc or ""
        tokens = d.split()
        new_tokens = []
        for t in tokens:
            tu = t.upper()
            if tu == "PC":
                new_tokens.append("PT")
            elif tu == "PT":
                new_tokens.append("PC")
            else:
                new_tokens.append(t)
        p.desc = " ".join(new_tokens)

    return pts[::-1]


def close_string_coding(last_point: SurveyPoint, code_prefix: str = "") -> SurveyPoint:
    """Update the end of a linework string to close back to start point (adds CLS)."""
    orig = last_point.desc or ""
    tokens = orig.split()
    new_tokens = []
    replaced = False
    for t in tokens:
        if t.upper() in END_FLAGS or t.upper() in CLOSE_FLAGS:
            new_tokens.append("CLS")
            replaced = True
        else:
            new_tokens.append(t)
    if not replaced:
        new_tokens.append("CLS")
    last_point.desc = " ".join(new_tokens)
    return last_point


def open_string_coding(last_point: SurveyPoint, code_prefix: str = "") -> SurveyPoint:
    """Update a closed linework string to open/unclosed (changes CLS to END)."""
    orig = last_point.desc or ""
    tokens = orig.split()
    new_tokens = []
    replaced = False
    for t in tokens:
        if t.upper() in CLOSE_FLAGS or t.upper() in END_FLAGS:
            new_tokens.append("END")
            replaced = True
        else:
            new_tokens.append(t)
    if not replaced:
        new_tokens.append("END")
    last_point.desc = " ".join(new_tokens)
    return last_point


def split_string_coding(points_before: Sequence[SurveyPoint],
                        points_after: Sequence[SurveyPoint],
                        new_string_id: str = "2") -> tuple[list[SurveyPoint], list[SurveyPoint]]:
    """Split a string at a point: ends segment 1 on points_before[-1] and starts segment 2 on points_after[0]."""
    if not points_before or not points_after:
        return list(points_before), list(points_after)

    p_end1 = points_before[-1]
    p_start2 = points_after[0]

    # End first segment: clean any existing start/end/close flags and append END
    desc_clean1 = re.sub(r"\b(CLS|CLOSE|ST|START|BEGIN|END|E|ED)\b", "", p_end1.desc or "", flags=re.IGNORECASE).strip()
    p_end1.desc = re.sub(r"\s+", " ", f"{desc_clean1} END").strip()

    # Determine base code for second segment
    tokens = (p_start2.desc or "").split()
    raw_code = tokens[0] if tokens else "EP"
    m = re.match(r"^([A-Za-z_-]+)(\d+)?$", raw_code)
    base_code = m.group(1) if m else raw_code
    new_prefix = f"{base_code}{new_string_id}"

    # Recode points in second segment with new string prefix
    modified_after = []
    for i, p in enumerate(points_after):
        token = f"{new_prefix} ST" if i == 0 else (f"{new_prefix} END" if i == len(points_after) - 1 else new_prefix)
        p.desc = update_point_token(p.desc or "", raw_code, token)
        modified_after.append(p)

    return list(points_before), modified_after


def change_string_code(points: Sequence[SurveyPoint], old_code_prefix: str, new_code_prefix: str) -> list[SurveyPoint]:
    """Change the code/prefix of an entire string while preserving commands (ST, PC, PT, END, CLS, etc.)."""
    modified = []
    old_pfx = old_code_prefix.strip().upper()
    new_pfx = new_code_prefix.strip().upper()

    for p in points:
        sub_tokens = [t.strip() for t in (p.desc or "").split("/") if t.strip()]
        new_sub = []
        replaced = False
        for tok in sub_tokens:
            tok_parts = tok.split()
            if tok_parts and tok_parts[0].upper() == old_pfx:
                tok_parts[0] = new_pfx
                new_sub.append(" ".join(tok_parts))
                replaced = True
            else:
                new_sub.append(tok)
        if not replaced and sub_tokens:
            # Check if any token starts with old_pfx
            new_sub_2 = []
            for tok in new_sub:
                tok_parts = tok.split()
                if tok_parts and tok_parts[0].upper().startswith(old_pfx):
                    tok_parts[0] = new_pfx
                    new_sub_2.append(" ".join(tok_parts))
                    replaced = True
                else:
                    new_sub_2.append(tok)
            new_sub = new_sub_2
        if not replaced and not sub_tokens:
            new_sub = [new_pfx]
        p.desc = " / ".join(new_sub)
        modified.append(p)
    return modified


def find_free_string_id(project: Project, base_code: str) -> str:
    """Find the next available unused numeric string ID for a given base code (e.g. EC -> 3 if EC1 and EC2 exist)."""
    used_ids = set()
    base_upper = base_code.strip().upper()
    pattern = re.compile(rf"\b{re.escape(base_upper)}(\d+)\b", re.IGNORECASE)

    for p in project.points.values():
        if not p.desc:
            continue
        for m in pattern.finditer(p.desc):
            used_ids.add(int(m.group(1)))

    # Find first positive integer not in used_ids
    candidate = 1
    while candidate in used_ids:
        candidate += 1
    return str(candidate)


def reorder_string_points(points: Sequence[SurveyPoint], new_order: Sequence[int], closed: bool = False) -> list[SurveyPoint]:
    """Reorder the points in a linework figure and re-assign start/end flags accordingly."""
    if not points or not new_order or len(points) != len(new_order):
        return list(points)

    reordered = [points[idx] for idx in new_order]
    tokens_first = (reordered[0].desc or "").split()
    base_prefix = tokens_first[0] if tokens_first else "EP"
    # Clean string ID / flags from base prefix
    m = re.match(r"^([A-Za-z_-]+)(\d+)?$", base_prefix)
    prefix = m.group(0) if m else base_prefix

    n = len(reordered)
    for i, p in enumerate(reordered):
        desc = p.desc or ""
        desc_clean = re.sub(r"\b(ST|START|BEGIN|END|CLS|CLOSE)\b", "", desc, flags=re.IGNORECASE).strip()
        desc_clean = re.sub(r"\s+", " ", desc_clean).strip()
        tokens = desc_clean.split()
        cur_code = tokens[0] if tokens else prefix

        if i == 0:
            token = f"{cur_code} ST"
        elif i == n - 1:
            token = f"{cur_code} {'CLS' if closed else 'END'}"
        else:
            token = cur_code

        p.desc = update_point_token(desc_clean, cur_code, token)

    return reordered


def merge_and_reclass_strings(project: Project, string1_points: Sequence[SurveyPoint],
                              string2_points: Sequence[SurveyPoint],
                              target_code: str = "", new_string_id: str | None = None,
                              closed: bool = False) -> list[SurveyPoint]:
    """Merge two line strings (e.g. EC1 and EC2) into a single continuous string with a clean string ID."""
    if not string1_points and not string2_points:
        return []
    if not string1_points:
        return list(string2_points)
    if not string2_points:
        return list(string1_points)

    pts1 = list(string1_points)
    pts2 = list(string2_points)

    # Determine base code
    if not target_code:
        tokens = (pts1[0].desc or "").split()
        raw = tokens[0] if tokens else "EP"
        m = re.match(r"^([A-Za-z_-]+)", raw)
        target_code = m.group(1).upper() if m else raw.upper()

    # Determine new string ID
    if new_string_id is None:
        new_string_id = find_free_string_id(project, target_code)

    new_prefix = f"{target_code}{new_string_id}"
    merged_pts = pts1 + pts2
    n = len(merged_pts)

    for i, p in enumerate(merged_pts):
        desc = p.desc or ""
        # Clean existing start/end/close flags
        desc_clean = re.sub(r"\b(ST|START|BEGIN|END|CLS|CLOSE)\b", "", desc, flags=re.IGNORECASE).strip()
        desc_clean = re.sub(r"\s+", " ", desc_clean).strip()
        tokens = desc_clean.split()
        old_token = tokens[0] if tokens else target_code

        if i == 0:
            token = f"{new_prefix} ST"
        elif i == n - 1:
            token = f"{new_prefix} {'CLS' if closed else 'END'}"
        else:
            token = new_prefix

        p.desc = update_point_token(desc_clean, old_token, token)

    return merged_pts


def swap_parallel_line_codes(points: Sequence[SurveyPoint], code_prefix1: str, code_prefix2: str) -> list[SurveyPoint]:
    """Swap feature code prefixes between two parallel line strings across specified points (fixes bowtie rod swaps)."""
    c1 = code_prefix1.strip().upper()
    c2 = code_prefix2.strip().upper()
    modified = []

    for p in points:
        desc = p.desc or ""
        if not desc:
            continue
        parts = [part.strip() for part in desc.split("/") if part.strip()]
        new_parts = []
        changed = False

        for part in parts:
            tokens = part.split()
            if not tokens:
                new_parts.append(part)
                continue
            head = tokens[0].upper()
            if head == c1 or head.startswith(c1):
                # Replace prefix with c2
                rest_tok = tokens[1:]
                new_parts.append(" ".join([c2] + rest_tok))
                changed = True
            elif head == c2 or head.startswith(c2):
                # Replace prefix with c1
                rest_tok = tokens[1:]
                new_parts.append(" ".join([c1] + rest_tok))
                changed = True
            else:
                new_parts.append(part)

        if changed:
            p.desc = " / ".join(new_parts)
            modified.append(p)

    return modified


def fix_line_command_order(desc: str) -> str:
    """Standardize linework command order in a description (ST before curve commands, END/CLS at the end)."""
    if not desc:
        return ""
    parts = [part.strip() for part in desc.split("/") if part.strip()]
    fixed_parts = []

    for part in parts:
        tokens = part.split()
        if len(tokens) <= 1:
            fixed_parts.append(part)
            continue

        code_tok = tokens[0]
        sub_tokens = tokens[1:]

        st_flags = []
        curve_flags = []
        end_flags = []
        other_tokens = []

        for t in sub_tokens:
            tu = t.upper()
            if tu in BEGIN_FLAGS or tu in ("ST", "START", "B", "BEGIN"):
                st_flags.append(tu)
            elif tu in ("PC", "PT", "ARC", "TAN"):
                curve_flags.append(tu)
            elif tu in END_FLAGS or tu in CLOSE_FLAGS or tu in ("END", "CLS", "CLOSE"):
                end_flags.append(tu)
            else:
                other_tokens.append(t)

        ordered = [code_tok] + st_flags + curve_flags + end_flags + other_tokens
        fixed_parts.append(" ".join(ordered))

    return " / ".join(fixed_parts)
