# utils_sort.py — natural sort keys (pure Python) + Qt table items
#
# The natural-sort KEY is used by the duplicate detectors, the linework builder and
# every "sort by point number" feature in both halves of the program.  None of that
# needs Qt, and the field-data core has to work on a machine with no Qt binding at all
# (CLI, tests, batch jobs), so the key below is pure Python and the two Qt table-item
# classes are defined only when Qt is actually available.
#
# Sorting rules (they are not the same rule, and that is deliberate):
#   point numbers -> letters first    EP2  before EP10,  1,2,10 (not 1,10,2)
#   descriptions  -> numbers first    "18 OAK" before "TREE"
#   N / E / Z     -> truly numeric    never string-sorted, or 999 sorts after 1000
import re


def natural_key(s, letters_first: bool = True):
    """Sort key for "EP2" < "EP10" and "1" < "2" < "10".

    ``letters_first=True`` puts alphabetic runs before digit runs at each position,
    which is what point numbers want (EP2 before EP10, and a bare "2" before "EP2").
    ``letters_first=False`` puts the digits first, which is what descriptions want
    ("18 OAK" sorts before "BLDG").
    """
    if s is None:
        return []
    text = str(s)
    parts = re.split(r'(\d+)', text)
    key_list = []
    digit_code = 1 if letters_first else 0
    letter_code = 0 if letters_first else 1
    for p in parts:
        if not p:
            continue
        if p.isdigit():
            key_list.append((digit_code, int(p)))
        else:
            key_list.append((letter_code, p.lower()))
    return key_list


def point_number_key(number):
    """Natural key for a point number, letters first."""
    return natural_key(number, letters_first=True)


def description_key(desc):
    """Natural key for a description, numbers first."""
    return natural_key(desc, letters_first=False)


def numeric_key(value_data, fallback=float("inf")):
    """Key for N / E / Z - a real number, never a string.

    Unparseable values (blank, "N/A") sort to the end rather than to zero, so a hole
    in the data does not look like the lowest elevation on the job.
    """
    try:
        return (0, float(str(value_data).strip()))
    except (TypeError, ValueError):
        return (1, fallback)


# ------------------------------------------------------------------------------------- Qt table items
# The two classes below are how the tables in the Fieldwork Manager window sort
# themselves.  They exist only when a Qt binding is importable; on a headless machine
# everything above still works and the names are placeholders that explain themselves.
try:
    from PySide6.QtWidgets import QTableWidgetItem as _QTableWidgetItem
except Exception:                                             # no Qt binding installed
    _QTableWidgetItem = None


if _QTableWidgetItem is not None:

    class NaturalSortItem(_QTableWidgetItem):
        """A table cell that sorts naturally (EP2 before EP10) instead of alphabetically."""

        def __init__(self, text="", letters_first=True):
            super().__init__(text)
            self.letters_first = letters_first

        def __lt__(self, other):
            if not isinstance(other, _QTableWidgetItem):
                return False
            return (natural_key(self.text(), self.letters_first)
                    < natural_key(other.text(), getattr(other, 'letters_first', self.letters_first)))


    class NumericSortItem(_QTableWidgetItem):
        """A table cell that sorts as a number, and shows the text it was given."""

        def __init__(self, value=None):
            super().__init__()
            self._numeric_value = None
            if value is not None:
                self.set_value(value)

        def set_value(self, value):
            if value is None:
                self._numeric_value = None
                return
            s = str(value).strip()
            if s == "":
                self._numeric_value = None
                return
            try:
                self._numeric_value = float(s)
            except (ValueError, TypeError):
                self._numeric_value = None

        def numeric_value(self):
            return self._numeric_value

        def __lt__(self, other):
            if not isinstance(other, NumericSortItem):
                return super().__lt__(other)
            left, right = self._numeric_value, other._numeric_value
            if left is None and right is None:
                return False
            if left is None:
                return False
            if right is None:
                return True
            return left < right

else:

    class _NeedsQt:
        """Placeholder that explains itself rather than failing with a bare ImportError."""

        def __init__(self, *a, **k):
            raise ImportError(
                "plumbline.fieldwork.utils_sort natural-sort table items need a Qt binding "
                "(PySide6). The sort keys and all of the field-data checks work without Qt; "
                "only the table widgets need it. Install PySide6 to use the window.")

    NaturalSortItem = _NeedsQt
    NumericSortItem = _NeedsQt
