"""The licence and the end-user agreement, in one place, in the order they are read.

Three documents live here, and they are **the** copy: ``LICENSE.md`` and ``EULA.md`` at the root
of the distribution are written from these strings (``python -m plumbline licence --write``) and a
test compares the shipped files byte-for-byte with what this module produces.  A licence that says
one thing in the installer and another thing on disk is worse than no licence at all.

**Part 1 - the licence.  Commercial use is the first thing said, not a footnote.**  This build is
published for testing and private use.  Commercial use is *not* granted, and everything else in
Part 2 is subordinate to that: the general agreement is written second because a reader who wants
to know whether they may use the program at work should get that answer from the first paragraph.

**Part 2 - the general end-user agreement** (the EULA): acceptance, what the software is and what
it is not, third-party data and services, no warranty, liability, and the commercial-use clause
restated where a reader of the long document will see it.

Nothing here is legal advice and no text here can make an untested program fit for a deliverable:
see "not a substitute for professional judgement" in Part 2, which is the sentence that matters
most to a surveyor.
"""
from __future__ import annotations

from pathlib import Path

#: Bump when the text changes.  The accept-on-first-run dialog is shown again when this changes,
#: so a user cannot be held to terms they were never shown (the previous acceptance is stored with
#: the version it applied to).
VERSION = 1

PUBLISHER = "the Plumbline authors"


# --------------------------------------------------------------------------------------------- part 1
COMMERCIAL_TERMS_TITLE = "Part 1 - Licence: testing and private use only; no commercial use"

COMMERCIAL_TERMS = """\
**This is a limited licence, and the limitation is the point of it.**

1. **No commercial use.** The Software is licensed for **non-commercial use only**. You may not
   use it, in whole or in part, for any commercial purpose or in any commercial context, including
   (without limitation): producing work product for a client or an employer; any use in the course
   of a trade, business, profession or revenue-generating activity; any use by a business entity
   or by an employee on behalf of one; any paid or resold service, deliverable or data product
   that was produced using it; or any use intended to lead to any of the above. Commercial use
   requires a separate written licence from {publisher}, and none is granted by this document.

2. **Testing and private use are what is granted.** You may install and run the Software to
   evaluate it, to test it, to learn from it, and for your own private, non-commercial purposes.
   You may copy it for those purposes and you may share it under the terms of Part 2 below.

3. **No professional-deliverable guarantee.** Testing use is testing use. Nothing in this licence
   makes the Software a substitute for professional judgement, for checking your own work, or for
   the standards your client, agency or licence requires.

4. **Everything else is in Part 2.** The general end-user agreement follows and applies in full.
   Where Part 1 and Part 2 could conflict, **Part 1 wins** - the non-commercial limitation is not
   narrowed by anything later in this document.
""".format(publisher=PUBLISHER)


# --------------------------------------------------------------------------------------------- part 2
EULA_TITLE = "Part 2 - General end-user licence agreement (EULA)"

EULA = """\
**1. Acceptance.** By installing, copying, running or distributing the Software you agree to this
agreement in full. If you do not agree, do not install or run the Software.

**2. What is licensed.** The Software is licensed, not sold. You receive a non-exclusive,
non-transferable, revocable permission to run it for **testing and private, non-commercial use
only** - see Part 1 above, which is the first part of this agreement and the part that governs
commercial use. Commercial use is expressly excluded and requires a separate written licence from
{publisher}.

**3. Third-party libraries, data and services.** The Software uses third-party components
(PySide6/Qt, PROJ and pyproj, ezdxf, shapely, numpy, scipy, openpyxl and others), each under its
own licence, and is distributed with CRS, vertical-datum and geoid-model **definitions** published
by others (the EPSG register, NOAA/NGS, USGS and PROJ). Imagery, map tiles, elevation and geoid
data may be fetched from third-party services at your request; those services are governed by
**their** terms, not by this agreement, and their attribution must be preserved. Some third-party
data is restricted from commercial use - the non-commercial limitation in Part 1 exists in part
because of that, and it is your responsibility to comply with each source's terms.

**4. Your data.** Your field data, coordinates, projects and outputs remain yours. The Software
runs locally and does not transmit your data anywhere except to the services you explicitly ask it
to fetch from.

**5. No warranty.** THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE, ACCURACY OF COORDINATE CONVERSION, AND NON-INFRINGEMENT. **Not a substitute for
professional judgement:** coordinate systems, geoid models, transformations, surface adjustment
factors and checks can be wrong or incomplete, and the Software may contain errors; a licensed
surveyor, competent person or quality process must verify anything produced with it before that
work is relied on.

**6. Limitation of liability.** To the maximum extent permitted by law, {publisher} shall not be
liable for any claim, damages or other liability - whether in contract, tort or otherwise - arising
from, out of or in connection with the Software or its use, including any loss of data, loss of
profit, or cost of rework.

**7. Termination.** This agreement terminates automatically if you breach it, including by using
the Software commercially. On termination you must stop using it and delete all copies.

**8. Distribution.** You may pass the Software on unmodified, together with this agreement and the
licence in Part 1. You may not sublicense it, sell it, or offer it as part of a paid service.

**9. Changes.** New versions may carry revised terms; the version of this agreement you accepted is
recorded, and a revised agreement is presented for acceptance when it changes.

**10. Whole agreement.** Parts 1 and 2 together are the whole agreement. If a provision is held
unenforceable, the rest stands. Nothing here grants any right in the name, marks or goodwill of
{publisher}.
""".format(publisher=PUBLISHER)


# --------------------------------------------------------------------------------------------- the document
def document() -> str:
    """The two parts as one document, in the order they are read: commercial terms, then EULA."""
    return (
        "# Licence and End-User Agreement\n\n"
        f"Version {VERSION} - {PUBLISHER}\n\n"
        "*This build is published for **testing and private use**. Commercial use is not granted.*\n"
        "Part 1 says so first, in the terms that govern it; Part 2 is the general agreement and\n"
        "applies in full.\n\n"
        "---\n\n"
        f"## {COMMERCIAL_TERMS_TITLE}\n\n{COMMERCIAL_TERMS}\n"
        "---\n\n"
        f"## {EULA_TITLE}\n\n{EULA}"
    )


def write_files(folder) -> list[Path]:
    """Write LICENSE.md and EULA.md into *folder* from this one copy.  Returns what it wrote."""
    folder = Path(folder)
    written = []
    licence = folder / "LICENSE.md"
    licence.write_text(
        "# Licence (Part 1 of the agreement) - testing and private use only\n\n"
        f"Version {VERSION} - {PUBLISHER}\n\n"
        "*Commercial use is not granted. This is the first part of the agreement because it is the\n"
        "part the reader needs first.*\n\n"
        f"## {COMMERCIAL_TERMS_TITLE}\n\n{COMMERCIAL_TERMS}\n"
        "## The rest of the agreement\n\n"
        "The general end-user licence agreement is `EULA.md` (Part 2), and it applies in full.\n"
        "It restates the commercial-use limitation in its clause 2, and its clause 3 carries the\n"
        "third-party data restrictions that sit behind it.\n",
        encoding="utf-8")
    written.append(licence)
    eula = folder / "EULA.md"
    eula.write_text(
        "# End-User Licence Agreement (Part 2 of the agreement)\n\n"
        f"Version {VERSION} - {PUBLISHER}\n\n"
        "*Read Part 1 first (`LICENSE.md`): in testing and private use only; no commercial use.*\n\n"
        f"## {EULA_TITLE}\n\n{EULA}",
        encoding="utf-8")
    written.append(eula)
    return written


__all__ = ["VERSION", "PUBLISHER", "COMMERCIAL_TERMS", "COMMERCIAL_TERMS_TITLE", "EULA",
           "EULA_TITLE", "document", "write_files"]
