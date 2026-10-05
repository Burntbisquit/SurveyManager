# parse.py — description parsing, line order validation, F2F set
import re, math
from collections import defaultdict
from pathlib import Path
from .config import COMMAND_SET, MULTICODE_SEP, DESCRIPTION_SEP, _TOKEN_RE, _SLASH_RE
from .io_carlson import read_fwb_file  # avoid circular: io does not import parse

def _strip_trailing_digits(token: str):
    """Return (base, number_str) where base is token without trailing digits. If no trailing digits, number_str=''."""
    import re
    m = re.match(r'^(.*?)(\d+)$', token)
    if m:
        return m.group(1), m.group(2)
    return token, ""

def _is_command(tok: str, command_set=None) -> bool:
    cs = command_set if command_set is not None else COMMAND_SET
    # If still default, try to refresh from global (in case set_command_set_global was called)
    try:
        # Use get_command_set if available for dynamic
        from .config import get_command_set
        # If command_set is None and we have no explicit, we could keep global COMMAND_SET which may have been updated
        pass
    except Exception:
        pass
    return tok.strip().casefold() in cs

def _classify_tokens_sequential(raw_tokens, f2f_set, command_set=None, rules=None):
    """Classify list of raw alphanumeric tokens left-to-right with orphan-command rule.
    Returns list of dicts {raw, norm, type, status, base, line_num, attached_to, error}
    Types: code / command . Status: exact / line_instance / valid / orphan / unknown
    Now allows multiple commands per code (e.g., ec st pc) — each command attaches to most recent code until next code.
    """
    import re
    res = []
    last_was_valid_code_idx = None  # index in res of last valid code that can take commands
    for tok in raw_tokens:
        low = tok.strip().casefold()
        cs = command_set if command_set is not None else COMMAND_SET
        if low in cs:
            if last_was_valid_code_idx is not None:
                # attach to that code — keep latch for multiple commands per code (curve: st pc)
                res.append({"raw": tok, "norm": low, "type": "command", "status": "valid", "attached_to": last_was_valid_code_idx})
                # do NOT consume latch: allow ec st pc (st then pc both for ec) — only new code resets
            else:
                res.append({"raw": tok, "norm": low, "type": "command", "status": "orphan", "error": "OrphanCommand"})
                # stays None
        else:
            # try code
            if low in f2f_set:
                res.append({"raw": tok, "norm": low, "type": "code", "status": "exact", "base": low, "line_num": ""})
                last_was_valid_code_idx = len(res)-1
            else:
                base, num = _strip_trailing_digits(tok)
                base_low = base.strip().casefold()
                if num and base and base_low in f2f_set:
                    # Only strip if exact miss and base hit (your 2-step)
                    res.append({"raw": tok, "norm": low, "type": "code", "status": "line_instance", "base": base_low, "line_num": num})
                    last_was_valid_code_idx = len(res)-1
                else:
                    res.append({"raw": tok, "norm": low, "type": "code", "status": "unknown", "error": "UnknownCode"})
                    last_was_valid_code_idx = None
    return res

def _extract_tokens(code_part: str):
    """Extract alphanumeric tokens from a string, handling missing dash/spaces: NG- Ec1 -> [NG, Ec1]"""
    return _TOKEN_RE.findall(code_part)

def parse_desc_field(raw_desc: str, f2f_set, fieldbook_path=None, command_set=None, rules=None):
    """Parse a raw Description field into code_part / free_desc and classified tokens.
    Handles missing dash/spaces, case-insensitive, no leading strip, trailing strip only on fail.
    Returns dict with keys: raw, code_part, free_desc, code_tokens_classified, free_tokens_classified, flags, flag_detail, parsed_code_str
    Flags: list of strings like UnknownCode:xyz, OrphanCommand:st, MisplacedAfterSeparator:ec2 st
    """
    import re
    if raw_desc is None:
        raw_desc = ""
    raw = str(raw_desc)
    # Apply correction rules if provided (or load from fieldbook)
    if rules is None and fieldbook_path:
        try:
            from .config import get_correction_rules
            rules = get_correction_rules(fieldbook_path)
        except Exception:
            rules = None
    if rules:
        # Rules: list of [common_error, fix] — exact match case-insensitive, or substring?
        # We do exact match on whole raw stripped, and also token-level
        raw_stripped = raw.strip()
        for err, fix in rules:
            if not err or not fix:
                continue
            if raw_stripped.casefold() == err.casefold():
                raw = fix
                break
            # Also handle dash/space tolerant: compare normalized tokens
            # If raw contains err as token, replace that token
    # Resolve command_set
    if command_set is None:
        if fieldbook_path:
            try:
                from .config import get_command_set
                command_set = get_command_set(fieldbook_path)
            except Exception:
                command_set = COMMAND_SET
        else:
            command_set = COMMAND_SET
    # Empty description — flag as EmptyDescription
    if not raw.strip():
        return {
            "raw": raw,
            "code_part": "",
            "free_desc": "",
            "has_slash": False,
            "code_raw_tokens": [],
            "code_classified": [],
            "free_raw_tokens": [],
            "free_classified": [],
            "flags": ["EmptyDescription"],
            "flag_detail": "Empty description — no code, command, or free text (point will not draw)",
            "parsed_code_str": "",
            "misplaced_sets": [],
        }
    # Find first slash as code/free boundary: optional spaces around / (ONLY first instance left-to-right is separator)
    # Use regex search for slash
    m = re.search(r'\s*/\s*', raw)
    has_slash = False
    slash_spacing_error = False
    if m:
        # Use first slash occurrence only (left-to-right)
        parts = re.split(r'\s*/\s*', raw, maxsplit=1)
        code_part = parts[0].strip()
        free_desc = parts[1].strip() if len(parts) > 1 else ""
        has_slash = True
        # Check spacing: must be exactly " / " (space slash space) around first slash
        # Find index of first "/" in raw
        try:
            slash_idx = raw.index('/')
            before = raw[slash_idx-1] if slash_idx > 0 else ""
            after = raw[slash_idx+1] if slash_idx+1 < len(raw) else ""
            if before != " " or after != " ":
                slash_spacing_error = True
        except Exception:
            pass
    else:
        # Also handle raw containing "/" without optional spaces? The regex \s*/\s* already covers it, but if maxsplit fails, check direct "/"
        if "/" in raw:
            # Should not happen as \s*/\s* would have matched, but handle
            slash_idx = raw.index('/')
            parts = raw.split('/', 1)
            code_part = parts[0].strip()
            free_desc = parts[1].strip() if len(parts) > 1 else ""
            has_slash = True
            before = raw[slash_idx-1] if slash_idx > 0 else ""
            after = raw[slash_idx+1] if slash_idx+1 < len(raw) else ""
            if before != " " or after != " ":
                slash_spacing_error = True
        else:
            code_part = raw.strip()
            free_desc = ""
            has_slash = False
    # Extract tokens for code part
    code_raw_tokens = _extract_tokens(code_part)
    code_classified = _classify_tokens_sequential(code_raw_tokens, f2f_set, command_set=command_set, rules=rules)
    # Extract tokens for free_desc (for flagging misplaced)
    free_raw_tokens = _extract_tokens(free_desc) if has_slash else []
    free_classified = _classify_tokens_sequential(free_raw_tokens, f2f_set, command_set=command_set, rules=rules) if free_raw_tokens else []
    flags = []
    details = []
    # Unknown codes in code part
    for item in code_classified:
        if item.get("status") == "unknown":
            flags.append(f"UnknownCode:{item['raw']}")
            details.append(f"UnknownCode '{item['raw']}' not in F2F (tried {item['raw']} → base {item.get('base','')})")
        elif item.get("status") == "orphan":
            flags.append(f"OrphanCommand:{item['raw']}")
            details.append(f"OrphanCommand '{item['raw']}' without preceding code (e.g. ec1 st st → second st, st ec1 st → first st)")
    # Misplaced after slash: any code/command that is valid in free_desc is misplaced
    # Group free_desc valid code+command sets as one misplaced set
    # Walk free_classified to find valid code or valid command attached to code
    # For flag, collect contiguous valid sets: code (exact/line_instance) optionally followed by one valid command
    i = 0
    misplaced_sets = []
    while i < len(free_classified):
        item = free_classified[i]
        if item["type"] == "code" and item["status"] in ("exact","line_instance"):
            # start set
            set_tokens = [item["raw"]]
            # check if next is valid command attached to this code
            if i+1 < len(free_classified) and free_classified[i+1]["type"] == "command" and free_classified[i+1].get("status") == "valid" and free_classified[i+1].get("attached_to") == i:
                set_tokens.append(free_classified[i+1]["raw"])
                i += 2
            else:
                i += 1
            misplaced_str = " ".join(set_tokens)
            flags.append(f"MisplacedAfterSeparator:{misplaced_str}")
            details.append(f"MisplacedAfterSeparator '{misplaced_str}' after {DESCRIPTION_SEP.strip()} — move before {DESCRIPTION_SEP.strip()} (descriptions shouldn\'t contain codes)")
            misplaced_sets.append(misplaced_str)
        elif item["type"] == "command" and item["status"] == "valid":
            # orphan valid command without code in free_desc (should not happen as classify would mark orphan if no code)
            # But if free_desc has "st" alone after slash without code, it would be orphan, not misplaced set
            flags.append(f"OrphanAfterSeparator:{item['raw']}")
            details.append(f"OrphanCommand '{item['raw']}' after {DESCRIPTION_SEP.strip()} without code")
            i+=1
        elif item["type"] == "command" and item["status"] == "orphan":
            flags.append(f"OrphanAfterSeparator:{item['raw']}")
            details.append(f"OrphanCommand '{item['raw']}' after {DESCRIPTION_SEP.strip()} without preceding code")
            i+=1
        else:
            # unknown or orphan in free_desc: unknown in free_desc is just noise (tree on pavement), not flagged as misplaced unless it's a known code
            # So skip unknown codes in free_desc (they are noise, not F2F)
            i+=1
    # Also handle case where free_desc contains slash but no valid tokens -> no misplaced flags, free_desc is just free text
    # Flag slash spacing error (must be exactly " / " with single spaces) — only first slash checked
    if has_slash and slash_spacing_error:
        flags.append(f"SeparatorSpacingError:{DESCRIPTION_SEP.strip()}")
        details.append(f"SeparatorSpacingError '{DESCRIPTION_SEP.strip()}' should be spaced as '{DESCRIPTION_SEP}' (space separator space) — first separator is description separator")
    # Parsed code string for display: rebuild code_part tokens that were valid (exact/line_instance) + valid commands
    parsed_tokens = []
    for item in code_classified:
        if item["status"] in ("exact","line_instance"):
            parsed_tokens.append(item["raw"])
        elif item["status"] == "valid" and item["type"] == "command":
            parsed_tokens.append(item["raw"])
    parsed_code_str = "".join(f"({tok})" for tok in parsed_tokens) if parsed_tokens else ""
    # Also build free_desc display (original)
    return {
        "raw": raw,
        "code_part": code_part,
        "free_desc": free_desc,
        "has_slash": has_slash,
        "code_raw_tokens": code_raw_tokens,
        "code_classified": code_classified,
        "free_raw_tokens": free_raw_tokens,
        "free_classified": free_classified,
        "flags": flags,
        "flag_detail": "; ".join(details) if details else "",
        "parsed_code_str": parsed_code_str,
        "misplaced_sets": misplaced_sets,
    }

def _validate_line_command_order(working_rows, f2f_set, settings=None, fieldbook_path=None, command_set=None, rules=None):
    """Check line command order — per-code, line START/END must be outside curve START/END.

    Correct hierarchy (outside → inside): ST (Start Line, outer) → PC (Start Curve, inner) → PT (End Curve, inner) → END/X (End Line/Close, outer)
    Examples of correct: ST PC, PT END, PT X, ST PC PT END, ST END, ST PC PT X
    Flag when that order is violated per code within a single description.
    Also flags ST PT without PC, PC without ST, PT without PC, PC/ST after END/X.
    Keeps per-code reactors separate, so ec x and toc st are independent.
    """
    if settings is None:
        settings = {}
    # Cache rules if not provided but fieldbook_path given (avoid per-row file reads)
    if rules is None and fieldbook_path:
        try:
            from .config import get_correction_rules
            rules = get_correction_rules(fieldbook_path)
        except Exception:
            rules = None
    protect_st_pc = settings.get("protect_st_pc", True)
    protect_pt_end = settings.get("protect_pt_end", True)
    protect_pt_x = settings.get("protect_pt_x", True)
    protect_pc_after_end = settings.get("protect_pc_after_end", True)
    protect_st_after_end = settings.get("protect_st_after_end", False)

    from collections import defaultdict
    import re
    oid_flags = defaultdict(list)
    oid_details = defaultdict(list)
    # Store details globally for caller to retrieve
    _validate_line_command_order.details = oid_details
    order = {"st": 0, "pc": 1, "pt": 2, "end": 3, "x": 3}
    # For correction, define canonical order list for sorting
    canonical = ["st", "pc", "pt", "end", "x"]  # end/x same rank, keep end before x if both

    for idx, wr in enumerate(working_rows):
        oid = wr[0] if len(wr) > 0 else str(idx)
        raw_desc = wr[5] if len(wr) > 5 else ""
        parsed = parse_desc_field(raw_desc, f2f_set, fieldbook_path=fieldbook_path, command_set=command_set, rules=rules)
        cl = parsed["code_classified"]
        # Group by code: code norm -> list of cmd norms and their raw items
        code_to_cmds = defaultdict(list)
        code_to_cmd_indices = defaultdict(list)
        code_raw = {}
        for i, item in enumerate(cl):
            if item["type"] == "command" and item.get("status") == "valid" and "attached_to" in item:
                cidx = item["attached_to"]
                code_item = cl[cidx] if 0 <= cidx < len(cl) else None
                if code_item and code_item["type"] == "code":
                    line_id = code_item["raw"].strip().casefold()
                    code_to_cmds[line_id].append(item["norm"].casefold())
                    code_to_cmd_indices[line_id].append(i)
                    code_raw[line_id] = code_item["raw"]

        for line_id, cmds in code_to_cmds.items():
            if not cmds:
                continue
            # --- 1. Check for ST PT without PC (protect_st_pc) — line outside curve: ST must be before PC, PT before END ---
            if protect_st_pc and "st" in cmds and "pt" in cmds and "pc" not in cmds:
                oid_flags[oid].append(f"LineOrderError")
                oid_details[oid].append(f"line without curve start (line start/end must be outside curve — correct Start Line + Start Curve, End Curve + End Line) — '{raw_desc}'")

            # --- 4. Check out-of-order by rank (covers ST PC, PT END, PT X) ---
            ranks = [order.get(c, 99) for c in cmds]
            if ranks != sorted(ranks):
                # Build corrected by sorting cmds by rank (ST→PC→PT→END/X)
                # Keep stable for equal rank (end/x)
                sorted_pairs = sorted(zip(cmds, ranks), key=lambda x: x[1])
                sorted_cmds = [p[0] for p in sorted_pairs]
                # Avoid duplicate flag if already flagged for PC before ST (which is same as out of order)
                # Generate corrected description for this code's group
                # Find original command raws for this code
                orig_cmds_raw = [cl[i]["raw"] for i in code_to_cmd_indices[line_id]]
                orig_group = f"{code_raw[line_id]} {' '.join(orig_cmds_raw)}" if orig_cmds_raw else code_raw[line_id]
                corrected_group = f"{code_raw[line_id]} {' '.join(c.upper() for c in sorted_cmds)}" if sorted_cmds else code_raw[line_id]
                try:
                    corrected = re.sub(re.escape(orig_group), corrected_group, raw_desc, count=1, flags=re.I)
                except Exception:
                    corrected = raw_desc
                # Provide specific message showing correct outside hierarchy
                oid_flags[oid].append(f"LineOrderError")
                oid_details[oid].append(f"commands out of order {cmds} → {sorted_cmds} (line should start before curve starts and curves should end before lines end — e.g., Start Line → Start Curve → End Curve → End Line/Close) — '{raw_desc}' → '{corrected}'")
                # Skip further checks for this code to avoid duplicate flags
                continue

            # --- 5. Check PC/ST after END/X (protect) ---
            if cmds:
                # Find positions of END/X in cmds
                end_indices = [i for i, c in enumerate(cmds) if c in ("end", "x")]
                if end_indices:
                    first_end = min(end_indices)
                    # Any ST or PC after first END/X is wrong (should be before)
                    after_end = cmds[first_end+1:]
                    if protect_pc_after_end and any(c == "pc" for c in after_end):
                        oid_flags[oid].append(f"LineOrderError")
                        oid_details[oid].append(f"curve start after line end (curve start after line end — line outside curve) — '{raw_desc}'")
                    if protect_st_after_end and any(c == "st" for c in after_end):
                        oid_flags[oid].append(f"LineOrderError")
                        oid_details[oid].append(f"line start after line end (line start after line end) — '{raw_desc}'")
                    # Also flag END without preceding PT when curve was used (protect_pt_end)
                    if protect_pt_end and "end" in cmds and "pt" not in cmds and "pc" in cmds:
                        oid_flags[oid].append(f"LineOrderError")
                        oid_details[oid].append(f"line end without curve end (curve end missing before line end — correct End Curve + End Line) — '{raw_desc}'")
                    if protect_pt_x and "x" in cmds and "pt" not in cmds and "pc" in cmds:
                        oid_flags[oid].append(f"LineOrderError")
                        oid_details[oid].append(f"close without curve end (curve end missing before close — correct End Curve + Close) — '{raw_desc}'")

    return dict(oid_flags)

def build_f2f_set_from_fieldbook(fieldbook_path):
    """Load F2F .fwb and return set of code strings casefolded. Returns empty set if no file."""
    from pathlib import Path
    if not fieldbook_path or not Path(fieldbook_path).exists():
        return set()
    headers, rows = read_fwb_file(Path(fieldbook_path))
    if not headers or not rows:
        return set()
    # Code is column 0
    s = set()
    for r in rows:
        if len(r) > 0 and r[0].strip():
            s.add(r[0].strip().casefold())
    return s

