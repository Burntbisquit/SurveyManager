"""Example exporter: a text summary of how many points were collected per feature code."""
from collections import Counter

from plumbline.core.featurecodes import parse_description
from plumbline.plugins import exporter


@exporter("Feature-code summary (*.txt)", ".txt")
def write_summary(project, path, api):
    counts = Counter(parse_description(p.desc).code or "(none)" for p in project.points.values())
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Project: {project.name}\nPoints: {len(project.points)}\n\n")
        for code, n in counts.most_common():
            f.write(f"{code:<12}{n:>8}\n")
    api.log(f"Wrote {len(counts)} code(s) to {path}")
