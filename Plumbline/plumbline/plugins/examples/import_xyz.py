"""Example importer: plain whitespace-separated "X Y Z" files (.xyz) - e.g. lidar or grid exports.

Importers return an ImportBatch in the *file's* coordinates; Plumbline then asks which coordinate
system the file uses and applies it with the normal duplicate-number handling.
"""
from plumbline.core.model import ImportBatch, SurveyPoint
from plumbline.plugins import importer


@importer("XYZ text points (*.xyz)", [".xyz"])
def read_xyz(path, api):
    batch = ImportBatch()
    bad = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            t = line.split()
            if len(t) < 3:
                continue
            try:
                x, y, z = float(t[0]), float(t[1]), float(t[2])
            except ValueError:
                bad += 1
                continue
            batch.points.append(SurveyPoint(0, str(len(batch.points) + 1), x, y, z, "XYZ", "POINTS"))
    if bad:
        batch.messages.append(f"{bad} unreadable line(s) skipped")
    return batch
