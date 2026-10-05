"""Example command: round elevations of the selected points (or all points if none are selected).

Copy this file into your plugin folder (Plugins > Open plugin folder) and edit it - the menu entry
appears under Plugins > Tools the next time plugins are reloaded.
"""
from plumbline.plugins import Param, command


@command("Tools/Round elevations", params=[Param("decimals", int, 2, "Decimal places", minimum=0, maximum=6)],
         description="Round the elevation of the selected points (all points if nothing is selected).")
def round_elevations(api, decimals=2):
    pts = api.selected_points() or api.points()
    n = 0
    with api.edit("Round elevations"):
        for p in pts:
            if p.z == p.z:                     # skip NaN (no elevation)
                p.z = round(p.z, int(decimals))
                n += 1
    api.log(f"Rounded {n} elevation(s) to {decimals} decimals.")
