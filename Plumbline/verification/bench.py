"""Benchmark Plumbline's headline performance claims (README: 100k points)."""
import os
import sys
from pathlib import Path
import tempfile
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root (import plumbline.*)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from plumbline.core.project import Project
from plumbline.core.surface import build_tin, generate_contours
from plumbline.core.model import ImportBatch, SurveyPoint
from plumbline.core import qa

N = 100_000
rng = np.random.default_rng(42)

print(f"building a {N:,}-point synthetic point cloud ...")
x = rng.uniform(0, 2000, N)
y = rng.uniform(0, 2000, N)
z = 100 + 0.01 * x + 0.02 * y + rng.normal(0, 0.05, N)

t0 = time.perf_counter()
p = Project("Bench")
p.apply_batch(ImportBatch(points=[SurveyPoint(0, str(i + 1), x[i], y[i], z[i], "GS") for i in range(N)]))
t_import = time.perf_counter() - t0
print(f"  import (apply_batch)          {t_import:7.3f} s   (claim 0.14 s)")

t0 = time.perf_counter()
_, _ = p.point_arrays()
t_arrays = time.perf_counter() - t0
print(f"  point_arrays()                {t_arrays:7.3f} s")

t0 = time.perf_counter()
tin, rep = build_tin(np.column_stack([x, y, z]))
t_tin = time.perf_counter() - t0
print(f"  TIN build                     {t_tin:7.3f} s   (claim 1.3 s)   {rep.n_triangles:,} triangles")

t0 = time.perf_counter()
tin.prepare()
t_prep = time.perf_counter() - t0
print(f"  TIN point locator (prepare)   {t_prep:7.3f} s")

from plumbline.core.model import Surface
s = Surface(0, "Bench", tin.pts, tin.tris)
p.add_surface(s)

t0 = time.perf_counter()
r = generate_contours(p, s, 1.0, 5, 0.0, 0, True)
t_cont = time.perf_counter() - t0
print(f"  contours (1 ft)               {t_cont:7.3f} s   (claim 0.1 s)   -> {r['lines']:,} lines, {r['labels']:,} labels")

t0 = time.perf_counter()
res = tin.volume_to_datum(150.0)
t_vol = time.perf_counter() - t0
print(f"  volume to datum               {t_vol:7.3f} s   (claim 0.03 s)  cut={res.cut:,.0f} fill={res.fill:,.0f}")

t0 = time.perf_counter()
issues = qa.run_checks(p)
t_qa = time.perf_counter() - t0
print(f"  data-quality scan             {t_qa:7.3f} s   (claim 1 s)     {len(issues)} issues")

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "bench.plb")
    t0 = time.perf_counter()
    p.save(path)
    t_save = time.perf_counter() - t0
    sz = os.path.getsize(path) / 1e6
    print(f"  save                          {t_save:7.3f} s   (claim 0.9 s)   {sz:.1f} MB")
    t0 = time.perf_counter()
    q = Project.load(path)
    t_load = time.perf_counter() - t0
    print(f"  load                          {t_load:7.3f} s   (claim 0.5 s)")

    from plumbline.io import dxf_io
    t0 = time.perf_counter()
    st = dxf_io.write_dxf(os.path.join(d, "bench.dxf"), p,
                          dxf_io.DxfOptions(points_mode="point", include_contours=False))
    t_dxf = time.perf_counter() - t0
    print(f"  DXF export (points only)      {t_dxf:7.3f} s   (claim 6 s)     {st}")

    t0 = time.perf_counter()
    st2 = dxf_io.write_dxf(os.path.join(d, "bench2.dxf"), p, dxf_io.DxfOptions(include_contours=False))
    t_dxf2 = time.perf_counter() - t0
    print(f"  DXF export (with labels)      {t_dxf2:7.3f} s   (claim 47 s)    {st2}")

t0 = time.perf_counter()
blob = p.snapshot()
t_snap = time.perf_counter() - t0
print(f"  undo snapshot                 {t_snap:7.3f} s   (claim 0.6 s)   {len(blob)/1e6:.1f} MB")
t0 = time.perf_counter()
p.restore(blob)
print(f"  undo restore                  {time.perf_counter()-t0:7.3f} s")
