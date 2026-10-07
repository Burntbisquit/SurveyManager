# parse.py — description parsing, line order validation, F2F set
import re, math
from collections import defaultdict
from pathlib import Path
from .config import COMMAND_SET, _TOKEN_RE, get_command_map, get_command_set
from ..core.fieldbook_syntax import (
    COMMAND_MEANINGS,
    command_meanings,
    find_separator,
    separator_pattern,
    separator_spacing_is_valid,
    split_at_separator,
    spacing_preference,
)
from .io_carlson import read_fwb_file  # avoid circular: io does not import parse

def _strip_trailing_digits(token: str):
    """Return (base, number_str) where base is token without trailing digits. If no trailing digits, number_str=''."""
    import re
    m = re.match(r'^(.*?)(\d+)$', token)
    if m:
        return m.group(1), m.group(2)
    return token, ""

def _strip_leading_digits(token: str):
    """Return (number_str, base) where base is token without leading digits. If no leading digits, number_str=''."""
    import re
    m = re.match(r'^(\d+)(.*)$', token)
    if m:
        return m.group(1), m.group(2)
    return "", token

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

def _classify_tokens_sequential(raw_tokens, f2f_set, command_set=None, rules=None, commands=None):
    """Classify tokens and attach enabled Field Book commands to the preceding valid code."""
    result = []
    meanings = command_meanings(commands)
    last_code_idx = None
    for token in raw_tokens:
        low = token.strip().casefold()
        cs = command_set if command_set is not None else COMMAND_SET
        if low in cs:
            meaning = meanings.get(low, "")
            if last_code_idx is not None:
                result.append({"raw": token, "norm": low, "type": "command", "status": "valid",
                               "meaning": meaning, "attached_to": last_code_idx})
            else:
                result.append({"raw": token, "norm": low, "type": "command", "status": "orphan",
                               "meaning": meaning, "error": "OrphanCommand"})
            continue

        if low in f2f_set:
            result.append({"raw": token, "norm": low, "type": "code", "status": "exact",
                           "base": low, "line_num": ""})
            last_code_idx = len(result) - 1
            continue

        base, number = _strip_trailing_digits(token)
        base_low = base.strip().casefold()
        if number and base and base_low in f2f_set:
            result.append({"raw": token, "norm": low, "type": "code", "status": "line_instance",
                           "base": base_low, "line_num": number})
            last_code_idx = len(result) - 1
            continue

        lead_num, lead_base = _strip_leading_digits(token)
        lead_base_low = lead_base.strip().casefold()
        base2, number2 = _strip_trailing_digits(lead_base)
        base2_low = base2.strip().casefold()
        if lead_num and lead_base and (lead_base_low in f2f_set or
                                       (number2 and base2 and base2_low in f2f_set)):
            matched_base = lead_base_low if lead_base_low in f2f_set else base2_low
            result.append({"raw": token, "norm": low, "type": "code",
                           "status": "line_instance" if number2 else "exact", "base": matched_base,
                           "line_num": number2, "lead_num": lead_num})
            last_code_idx = len(result) - 1
        else:
            result.append({"raw": token, "norm": low, "type": "code", "status": "unknown",
                           "error": "UnknownCode"})
            last_code_idx = None
    return result


def _extract_tokens(code_part: str):
    """Extract alphanumeric tokens from a string, handling missing dash/spaces."""
    return _TOKEN_RE.findall(code_part)


def _is_known_code(token: str, f2f_set) -> bool:
    """Whether a token is an exact, numbered, or leading-number instance of an F2F code."""
    low = token.casefold()
    if low in f2f_set:
        return True
    base, number = _strip_trailing_digits(token)
    if number and base.casefold() in f2f_set:
        return True
    lead_num, lead_base = _strip_leading_digits(token)
    if lead_num and lead_base:
        if lead_base.casefold() in f2f_set:
            return True
        base, number = _strip_trailing_digits(lead_base)
        return bool(number and base.casefold() in f2f_set)
    return False


def _extract_semantic_tokens(text: str, f2f_set, command_set, commands=None) -> list[str]:
    """Extract codes and commands while respecting active separators and compact code-command pairs."""
    from .config import get_command_map

    meanings = command_meanings(commands)
    semantic_tokens = get_command_map(commands=commands)
    multicode = semantic_tokens.get("multicode", "")
    segments = split_at_separator(text, multicode, maxsplit=0) if multicode else [text]
    line_commands = {
        token for token, meaning in meanings.items()
        if meaning in COMMAND_MEANINGS[:5] and token in command_set
    }
    def split_compact(token, depth=0):
        low = token.casefold()
        if low in command_set or _is_known_code(token, f2f_set) or depth >= 8:
            return [token]
        for command in sorted(line_commands, key=len, reverse=True):
            if low.endswith(command) and len(token) > len(command):
                prefix = token[:-len(command)]
                split_prefix = split_compact(prefix, depth + 1)
                if split_prefix and split_prefix[0].casefold() not in command_set and _is_known_code(split_prefix[0], f2f_set):
                    return [*split_prefix, token[-len(command):]]
        return [token]

    extracted = []
    for segment in segments:
        for raw_token in _extract_tokens(segment):
            extracted.extend(split_compact(raw_token))
    return extracted

def parse_desc_field(raw_desc: str, f2f_set, fieldbook_path=None, command_set=None, rules=None, commands=None):
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
    # Resolve both command membership and semantic separator meanings from the same Field Book.
    try:
        semantic_commands = get_command_map(fieldbook_path, commands)
    except Exception:
        semantic_commands = get_command_map(commands=commands)
    if command_set is None:
        try:
            command_set = get_command_set(fieldbook_path, commands)
        except Exception:
            command_set = COMMAND_SET
    description_token = semantic_commands.get("description", "")
    multicode_token = semantic_commands.get("multicode", "")
    # Empty description — flag as EmptyDescription
    if not raw.strip():
        return {
            "raw": raw,
            "code_part": "",
            "free_desc": "",
            "has_slash": False,
            "has_description_separator": False,
            "has_multicode_separator": False,
            "code_raw_tokens": [],
            "code_classified": [],
            "free_raw_tokens": [],
            "free_classified": [],
            "flags": ["EmptyDescription"],
            "flag_detail": "Empty description — no code, command, or free text (point will not draw)",
            "parsed_code_str": "",
            "misplaced_sets": [],
        }
    # The Field Book meanings, not punctuation literals, define the two boundaries.
    separator_index = find_separator(raw, description_token)
    has_description_separator = separator_index >= 0
    if has_description_separator:
        parts = split_at_separator(raw, description_token, maxsplit=1)
        code_part = parts[0].strip()
        free_desc = parts[1].strip() if len(parts) > 1 else ""
        description_spacing_error = not separator_spacing_is_valid(
            raw, separator_index, description_token,
            spaced=spacing_preference("space_around_description_separator"),
        )
    else:
        code_part = raw.strip()
        free_desc = ""
        description_spacing_error = False

    # Check every multi-code separator in the code portion; notes may contain punctuation freely.
    multicode_region = raw[:separator_index] if has_description_separator else raw
    multicode_matches = list(re.finditer(separator_pattern(multicode_token), multicode_region,
                                             flags=re.IGNORECASE)) if multicode_token else []
    has_multicode_separator = bool(multicode_matches)
    multicode_spacing_error = any(
        not separator_spacing_is_valid(
            multicode_region, match.start(), multicode_token,
            spaced=spacing_preference("space_around_multicode_separator"),
        )
        for match in multicode_matches
    )
    # Retain the historical result key for callers that have not adopted semantic names yet.
    has_slash = has_description_separator
    # Extract tokens for code part
    code_raw_tokens = _extract_semantic_tokens(code_part, f2f_set, command_set, semantic_commands)
    code_classified = _classify_tokens_sequential(
        code_raw_tokens, f2f_set, command_set=command_set, rules=rules, commands=semantic_commands)
    # Extract tokens for free_desc (for flagging misplaced)
    free_raw_tokens = _extract_semantic_tokens(
        free_desc, f2f_set, command_set, semantic_commands) if has_slash else []
    free_classified = _classify_tokens_sequential(
        free_raw_tokens, f2f_set, command_set=command_set, rules=rules,
        commands=semantic_commands) if free_raw_tokens else []
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
    # Valid feature codes and commands after the description separator are misplaced
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
            details.append(f"Potential code '{misplaced_str}' appears after the description separator — move it before the separator.")
            misplaced_sets.append(misplaced_str)
        elif item["type"] == "command" and item["status"] == "valid":
            # orphan valid command without code in free_desc (should not happen as classify would mark orphan if no code)
            # A command by itself in free text is orphaned, not a misplaced code group.
            flags.append(f"OrphanAfterSeparator:{item['raw']}")
            details.append(f"Orphan command '{item['raw']}' after the description separator without a feature code.")
            i+=1
        elif item["type"] == "command" and item["status"] == "orphan":
            flags.append(f"OrphanAfterSeparator:{item['raw']}")
            details.append(f"Orphan command '{item['raw']}' after the description separator without a preceding feature code.")
            i+=1
        else:
            # unknown or orphan in free_desc: unknown in free_desc is just noise (tree on pavement), not flagged as misplaced unless it's a known code
            # So skip unknown codes in free_desc (they are noise, not F2F)
            i+=1
    # Unknown words in free text are ordinary notes; only recognized codes/commands are flagged.
    if multicode_spacing_error:
        flags.append("SeparatorSpacingError:multicode")
        expectation = "use exactly one space on each side" if spacing_preference("space_around_multicode_separator") else "have no surrounding spaces"
        details.append(f"Spacing around the multi-code separator should {expectation} (see Settings).")
    if has_description_separator and description_spacing_error:
        flags.append("SeparatorSpacingError:description")
        expectation = "use exactly one space on each side" if spacing_preference("space_around_description_separator") else "have no surrounding spaces"
        details.append(f"Spacing around the description separator should {expectation} (see Settings).")
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
        "has_description_separator": has_description_separator,
        "has_multicode_separator": has_multicode_separator,
        "separator_tokens": {"multicode": multicode_token, "description": description_token},
        "code_raw_tokens": code_raw_tokens,
        "code_classified": code_classified,
        "free_raw_tokens": free_raw_tokens,
        "free_classified": free_classified,
        "flags": flags,
        "flag_detail": "; ".join(details) if details else "",
        "parsed_code_str": parsed_code_str,
        "misplaced_sets": misplaced_sets,
    }

def _validate_line_command_order(working_rows, f2f_set, settings=None, fieldbook_path=None,
                                 command_set=None, rules=None, commands=None):
    """Check line-command order using the active Field Book's semantic command meanings."""
    if settings is None:
        settings = {}
    if rules is None and fieldbook_path:
        try:
            from .config import get_correction_rules
            rules = get_correction_rules(fieldbook_path)
        except Exception:
            rules = None
    try:
        from .config import get_command_map
        semantic_tokens = get_command_map(fieldbook_path, commands)
    except Exception:
        from ..core.fieldbook_syntax import command_map
        semantic_tokens = command_map(commands)
    meanings = command_meanings(semantic_tokens)

    protect_st_pc = settings.get("protect_st_pc", True)
    protect_pt_end = settings.get("protect_pt_end", True)
    protect_pt_x = settings.get("protect_pt_x", True)
    protect_pc_after_end = settings.get("protect_pc_after_end", True)
    protect_st_after_end = settings.get("protect_st_after_end", False)

    from collections import defaultdict
    from ..core.fieldbook_syntax import command_joiner

    oid_flags = defaultdict(list)
    oid_details = defaultdict(list)
    _validate_line_command_order.details = oid_details
    rank = {"start_line": 0, "start_curve": 1, "end_curve": 2,
            "end_line": 3, "close": 3}
    line_meanings = set(rank)
    spacing = command_joiner()

    for idx, working_row in enumerate(working_rows):
        oid = working_row[0] if len(working_row) > 0 else str(idx)
        raw_desc = working_row[5] if len(working_row) > 5 else ""
        parsed = parse_desc_field(
            raw_desc, f2f_set, fieldbook_path=fieldbook_path, command_set=command_set,
            rules=rules, commands=semantic_tokens)
        classified = parsed["code_classified"]
        code_to_commands = defaultdict(list)
        code_to_command_indices = defaultdict(list)
        code_raw = {}
        for item_index, item in enumerate(classified):
            if item["type"] != "command" or item.get("status") != "valid":
                continue
            meaning = item.get("meaning") or meanings.get(item.get("norm", "").casefold(), "")
            if meaning not in line_meanings or "attached_to" not in item:
                continue
            code_index = item["attached_to"]
            code_item = classified[code_index] if 0 <= code_index < len(classified) else None
            if code_item and code_item["type"] == "code":
                line_id = code_item["raw"].strip().casefold()
                code_to_commands[line_id].append(meaning)
                code_to_command_indices[line_id].append(item_index)
                code_raw[line_id] = code_item["raw"]

        for line_id, meanings_on_code in code_to_commands.items():
            if not meanings_on_code:
                continue
            if (protect_st_pc and "start_line" in meanings_on_code and
                    "end_curve" in meanings_on_code and "start_curve" not in meanings_on_code):
                oid_flags[oid].append("LineOrderError")
                oid_details[oid].append(
                    f"line without curve start (line start/end must be outside curve) — '{raw_desc}'")

            ranks = [rank.get(meaning, 99) for meaning in meanings_on_code]
            if ranks != sorted(ranks):
                sorted_meanings = [meaning for meaning, _ in sorted(
                    zip(meanings_on_code, ranks), key=lambda pair: pair[1])]
                original_command_tokens = [classified[i]["raw"]
                                           for i in code_to_command_indices[line_id]]
                original_parts = [code_raw[line_id], *original_command_tokens]
                pattern = (r"(?<![A-Za-z0-9_])" +
                           r"\s*".join(re.escape(part) for part in original_parts) +
                           r"(?![A-Za-z0-9_])")
                corrected_tokens = [semantic_tokens.get(meaning, "") for meaning in sorted_meanings]
                corrected_parts = [code_raw[line_id], *[t for t in corrected_tokens if t]]
                corrected_group = spacing.join(corrected_parts)
                corrected = re.sub(pattern, corrected_group, raw_desc, count=1, flags=re.IGNORECASE)
                oid_flags[oid].append("LineOrderError")
                oid_details[oid].append(
                    f"commands out of semantic order {meanings_on_code} → {sorted_meanings} "
                    f"(Start Line → Start Curve → End Curve → End Line/Close) — "
                    f"'{raw_desc}' → '{corrected}'")
                continue

            end_meanings = {"end_line", "close"}
            end_indices = [i for i, meaning in enumerate(meanings_on_code) if meaning in end_meanings]
            if end_indices:
                first_end = min(end_indices)
                after_end = meanings_on_code[first_end + 1:]
                if protect_pc_after_end and "start_curve" in after_end:
                    oid_flags[oid].append("LineOrderError")
                    oid_details[oid].append(
                        f"curve start after line end (line command order) — '{raw_desc}'")
                if protect_st_after_end and "start_line" in after_end:
                    oid_flags[oid].append("LineOrderError")
                    oid_details[oid].append(
                        f"line start after line end (line command order) — '{raw_desc}'")
                if (protect_pt_end and "end_line" in meanings_on_code and
                        "end_curve" not in meanings_on_code and "start_curve" in meanings_on_code):
                    oid_flags[oid].append("LineOrderError")
                    oid_details[oid].append(
                        f"line end without curve end (End Curve must precede End Line) — '{raw_desc}'")
                if (protect_pt_x and "close" in meanings_on_code and
                        "end_curve" not in meanings_on_code and "start_curve" in meanings_on_code):
                    oid_flags[oid].append("LineOrderError")
                    oid_details[oid].append(
                        f"close without curve end (End Curve must precede Close) — '{raw_desc}'")

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

