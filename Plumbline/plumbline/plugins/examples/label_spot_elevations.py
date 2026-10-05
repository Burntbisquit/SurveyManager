"""Example command: drop spot-elevation text next to the selected points (all points if none selected)."""
from plumbline.plugins import Param, command


@command("Tools/Label spot elevations",
         params=[Param("height", float, 2.0, "Text height (drawing units)", minimum=0.01),
                 Param("decimals", int, 2, "Decimal places", minimum=0, maximum=4),
                 Param("layer", str, "SPOT-ELEV", "Layer")])
def label_spots(api, height=2.0, decimals=2, layer="SPOT-ELEV"):
    pts = [p for p in (api.selected_points() or api.points()) if p.z == p.z]
    with api.edit("Label spot elevations"):
        api.project.ensure_layer(layer, (0, 255, 255))
        api.project.remove_derived("spots")            # re-running replaces the previous labels
        for p in pts:
            t = api.project.add_text(p.x + height * 0.6, p.y + height * 0.3, f"{p.z:.{int(decimals)}f}",
                                     height, 0.0, layer, derived="spots")
    api.log(f"Added {len(pts)} spot elevation label(s).")
