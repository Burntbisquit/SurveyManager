"""Colour ramps shared by the plan view (ui/render.py) and the 3D renderer (core/scene3d.py)."""
from __future__ import annotations

import numpy as np

RAMPS = {
    "dark": {"elev": [(30, 52, 84), (36, 88, 104), (58, 114, 100), (100, 134, 90), (150, 146, 88), (170, 124, 84), (196, 176, 156)],
             "slope": [(52, 112, 84), (92, 134, 78), (150, 146, 70), (172, 124, 62), (176, 92, 56), (160, 62, 60), (112, 44, 92)]},
    "light": {"elev": [(140, 176, 208), (146, 200, 196), (168, 214, 168), (212, 222, 158), (232, 204, 148), (224, 170, 140), (240, 230, 220)],
              "slope": [(150, 208, 166), (190, 220, 150), (236, 226, 140), (242, 196, 130), (236, 160, 120), (222, 124, 120), (190, 120, 176)]},
}
SLOPE_EDGES = np.array([2, 5, 10, 15, 25, 33, 50.0])


def lut(ramp, n=256):
    r = np.array(ramp, float)
    pos = np.linspace(0, 1, len(r))
    t = np.linspace(0, 1, n)
    return np.column_stack([np.interp(t, pos, r[:, k]) for k in range(3)])
