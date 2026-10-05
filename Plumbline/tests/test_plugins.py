import math

import pytest

from plumbline import plugins as P
from plumbline.core.project import Project


@pytest.fixture()
def plugin_home(tmp_path, monkeypatch):
    from plumbline.core import settings as S
    monkeypatch.setenv("PLUMBLINE_HOME", str(tmp_path))
    S._SETTINGS = None if hasattr(S, "_SETTINGS") else None
    P.registry.clear()
    return tmp_path


def make_project():
    pr = Project("p")
    for i in range(4):
        pr.add_point(i, i, 10.123456 + i, desc="GS")
    return pr


def test_install_examples_and_load(plugin_home):
    names = P.install_examples()
    assert {"round_elevations.py", "import_xyz.py", "export_code_summary.py", "label_spot_elevations.py"} <= set(names)
    errs = P.load_plugins()
    assert errs == []
    paths = {c.path for c in P.registry.commands}
    assert {"Tools/Round elevations", "Tools/Label spot elevations"} <= paths
    assert [i.extensions for i in P.registry.importers] == [[".xyz"]]
    assert [e.extension for e in P.registry.exporters] == [".txt"]
    # installing again does not overwrite user edits
    (P.plugin_dir() / "round_elevations.py").write_text("# edited\n")
    assert P.install_examples() == []


def test_commands_run_with_undo_aware_edit(plugin_home):
    P.install_examples()
    P.load_plugins()
    pr = make_project()
    api = P.PluginAPI(pr, log=lambda s: None)
    cmd = next(c for c in P.registry.commands if c.name == "Round elevations")
    P.run_command(cmd, api, {"decimals": 1})
    assert [p.z for p in pr.points.values()] == [10.1, 11.1, 12.1, 13.1]
    lab = next(c for c in P.registry.commands if c.name == "Label spot elevations")
    P.run_command(lab, api, {"height": 1.0, "decimals": 2, "layer": "SPOT"})
    P.run_command(lab, api, {"height": 1.0, "decimals": 2, "layer": "SPOT"})      # rerun replaces
    assert sum(1 for e in pr.entities.values() if getattr(e, "text", None)) == 4


def test_exporter_and_importer_plugins(plugin_home, tmp_path):
    P.install_examples()
    P.load_plugins()
    pr = make_project()
    api = P.PluginAPI(pr, log=lambda s: None)
    out = tmp_path / "s.txt"
    P.registry.exporters[0].func(pr, out, api)
    assert "GS" in out.read_text() and "Points: 4" in out.read_text()
    f = tmp_path / "a.xyz"
    f.write_text("1 2 3\n4 5 6\nbad line here\n7 8 x\n")
    b = P.registry.importers[0].func(f, api)
    assert len(b.points) == 2 and b.messages and b.points[1].z == 6.0


def test_broken_plugin_is_isolated(plugin_home):
    d = P.plugin_dir()
    (d / "good.py").write_text("from plumbline.plugins import command\n@command('A/Good')\ndef g(api): pass\n")
    (d / "bad.py").write_text("from plumbline.plugins import command\n@command('A/Half')\ndef h(api): pass\nraise RuntimeError('boom')\n")
    (d / "syntax.py").write_text("def broken(:\n")
    (d / "_private.py").write_text("raise RuntimeError('never loaded')\n")
    errs = P.load_plugins()
    assert sorted(e[0].rsplit("/", 1)[-1] for e in errs) == ["bad.py", "syntax.py"]
    assert "boom" in dict(errs)[str(d / "bad.py")]
    assert [c.path for c in P.registry.commands] == ["A/Good"]      # the half-loaded file registered nothing


def test_run_script_scope_and_errors(plugin_home, tmp_path):
    pr = make_project()
    logs = []
    s = tmp_path / "s.py"
    s.write_text("print('n =', len(project.points))\nwith api.edit('x'):\n    project.add_point(9, 9, 9)\nprint(np.pi > 3, cogo.azimuth_deg(1, 1))\n")
    assert P.run_script(s, pr, log=logs.append) is None
    assert len(pr.points) == 5 and logs[0] == "n = 4" and "45.0" in logs[1]
    bad = tmp_path / "b.py"
    bad.write_text("x = 1 / 0\n")
    err = P.run_script(bad, pr, log=logs.append)
    assert err and "ZeroDivisionError" in err
