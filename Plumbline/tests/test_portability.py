"""Things that matter when Plumbline runs somewhere other than the Linux box it was written on (mainly Windows):
`plumbline doctor`, opening a file from the command line, explicit text encodings, fonts, the .bat launchers."""
import ast
import builtins
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------------------------------------- doctor
def test_doctor_reports_everything_ok(capsys):
    from plumbline import doctor
    assert doctor.run() == 0
    out = capsys.readouterr().out
    assert "Everything Plumbline needs is installed and working." in out
    for lib in ("PySide6", "numpy", "scipy", "shapely", "pyproj", "ezdxf", "pyogrio", "matplotlib", "openpyxl", "Pillow"):
        assert f"ok        {lib}" in out, lib
    assert "ok        Plumbline" in out
    assert out.isascii()                                  # must print in any Windows console


def test_doctor_is_reachable_from_the_command_line(capsys):
    from plumbline import cli
    assert cli.main(["doctor"]) == 0
    assert "Plumbline 0.1.0" in capsys.readouterr().out


def _break_import(monkeypatch, package: str, message: str):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == package or name.startswith(package + "."):
            raise ImportError(message)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_doctor_explains_a_missing_visual_cpp_runtime(monkeypatch, capsys):
    from plumbline import doctor
    _break_import(monkeypatch, "shapely", "DLL load failed while importing lib: The specified module could not be found.")
    code = doctor.run()
    monkeypatch.undo()
    out = capsys.readouterr().out
    assert code == 1
    assert "PROBLEM   shapely" in out
    assert "Visual C++" in out and "vc_redist.x64.exe" in out
    assert "Everything Plumbline needs" not in out


def test_doctor_says_which_library_is_not_installed():
    from plumbline import doctor
    assert "not installed" in doctor.explain("scipy", ModuleNotFoundError("No module named 'scipy'"))
    assert "send me this whole output" in doctor.explain("scipy", RuntimeError("boom"))


def test_doctor_treats_geotiff_support_as_optional(monkeypatch, capsys):
    from plumbline import doctor
    _break_import(monkeypatch, "rasterio", "No module named 'rasterio'")
    code = doctor.run()
    monkeypatch.undo()
    out = capsys.readouterr().out
    assert code == 0
    assert "optional  rasterio" in out and "PNG/JPG with a world file" in out


def test_doctor_notes_settings_left_by_other_gis_programs(monkeypatch, capsys):
    from plumbline import doctor
    monkeypatch.setenv("GDAL_DRIVER_PATH", r"C:\Program Files\QGIS 3.40\bin\gdalplugins")
    assert doctor.run() == 0
    out = capsys.readouterr().out
    assert "Note: GDAL_DRIVER_PATH is set" in out and "Plumbline.bat does that for you" in out


# ------------------------------------------------------------------------------------- a file name on the command line
def test_a_bare_file_name_opens_that_file(monkeypatch):
    """`plumbline job.plb` (and dragging a project onto Plumbline.bat) must reach the GUI with that path."""
    from plumbline import cli
    seen = []
    monkeypatch.setattr(cli, "_gui", lambda p: seen.append(p) or 0)
    assert cli.main(["job.plb"]) == 0
    assert cli.main([r"C:\Users\me\My Jobs\lot 7.plb"]) == 0
    assert cli.main([]) == 0
    assert seen == ["job.plb", r"C:\Users\me\My Jobs\lot 7.plb", None]


def test_commands_still_work_and_a_stray_file_before_one_is_refused(monkeypatch, capsys):
    from plumbline import cli
    monkeypatch.setattr(cli, "_gui", lambda p: pytest.fail("the GUI must not start for a command"))
    assert cli.main(["doctor"]) == 0
    with pytest.raises(SystemExit) as exc:
        cli.main(["job.plb", "doctor"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0


# ------------------------------------------------------------------------------------------------ text encodings
def _text_io_without_encoding() -> list[str]:
    """Every text-mode open() / read_text() / write_text() in the package that does not name an encoding."""
    bad = []
    for path in sorted((ROOT / "plumbline").rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn, kws = node.func, {k.arg: k.value for k in node.keywords}
            if isinstance(fn, ast.Name) and fn.id == "open":                       # the builtin open()
                mode = kws.get("mode", node.args[1] if len(node.args) > 1 else None)
                mode = mode.value if isinstance(mode, ast.Constant) else ""
                if "b" not in mode and "encoding" not in kws and len(node.args) < 4:
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno}  {ast.unparse(node)[:80]}")
            elif isinstance(fn, ast.Attribute) and fn.attr in ("read_text", "write_text"):
                needed = 1 if fn.attr == "read_text" else 2                        # encoding may be positional
                if "encoding" not in kws and len(node.args) < needed:
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno}  {ast.unparse(node)[:80]}")
    return bad


def test_every_text_file_read_or_write_names_its_encoding():
    """Windows opens text files as cp1252 unless told otherwise, so a plain open(path) can crash on a degree sign or an
    accented layer name. Say utf-8 (or utf-8-sig for CSVs meant for Excel) every time."""
    bad = _text_io_without_encoding()
    assert not bad, "text I/O without an explicit encoding:\n  " + "\n  ".join(bad)


def test_csv_reader_handles_windows_ansi_and_excel_utf8_files(tmp_path):
    from plumbline.io import csv_points
    f = tmp_path / "pts.csv"
    f.write_bytes("1,100.0,200.0,50.0,FH \u00b0 MANHOLE\r\n2,101.0,201.0,51.0,TREE \u00e9\r\n".encode("cp1252"))   # Windows "ANSI" file
    text, enc = csv_points.read_text(f)
    assert enc == "cp1252" and "\u00b0" in text and "\u00e9" in text
    g = tmp_path / "pts_utf8.csv"
    g.write_bytes(b"\xef\xbb\xbf" + "1,100.0,200.0,50.0,FH \u00b0\r\n".encode("utf-8"))                              # Excel "CSV UTF-8"
    text, enc = csv_points.read_text(g)
    assert enc == "utf-8-sig" and text.startswith("1,100.0") and "\u00b0" in text


# ------------------------------------------------------------------------------------ Python version policy
def test_doctor_accepts_3_13_and_3_14_and_warns_about_older():
    from plumbline import doctor
    # 3.14 is the version this release is built against: no problem, no note
    assert doctor.python_version_issues((3, 14, 8, "final", 0)) == ([], [])
    # 3.13 passes the test suite too - supported, but say which version was tested
    problems, notes = doctor.python_version_issues((3, 13, 16, "final", 0))
    assert not problems and len(notes) == 1 and "3.14" in notes[0]
    # anything newer is allowed with a caution about wheels
    problems, notes = doctor.python_version_issues((3, 15, 0, "final", 0))
    assert not problems and len(notes) == 1 and "3.14" in notes[0]
    # older than the floor is the only hard failure
    for old in ((3, 12, 9, "final", 0), (3, 11, 7, "final", 0), (2, 7, 18, "final", 0)):
        problems, notes = doctor.python_version_issues(old)
        assert len(problems) == 1 and "too old" in problems[0] and "3.14" in problems[0] and not notes
    # whatever interpreter the tests run on must itself be acceptable
    assert doctor.python_version_issues() == ([], []) or doctor.python_version_issues()[1], \
        "the test interpreter must satisfy the declared Python policy"


def test_the_project_declares_the_supported_python_range():
    import tomllib
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert meta["requires-python"] == ">=3.13"
    assert meta["classifiers"] == ["Programming Language :: Python :: 3.13",
                                   "Programming Language :: Python :: 3.14"]
    setup = (ROOT / "install_windows.bat").read_text("ascii")
    # the installer must actually try 3.14 first and fall back to 3.13
    assert 'PYVER=3.14' in setup and 'PYVER=3.13' in setup and "py -%PYVER% -m venv" in setup
    for other in ("3.10", "3.11", "3.12", "3.15"):
        assert other not in setup, f"install_windows.bat still mentions Python {other}"
    guide = (ROOT / "docs" / "WINDOWS_SETUP.md").read_text("utf-8")
    assert "3.13" in guide, "the Windows guide should mention that 3.13 also works"


def test_requirements_txt_and_pyproject_list_the_same_minimums():
    """Two places name the libraries (pip install -r requirements.txt, pip install -e .): keep them identical."""
    import tomllib
    from packaging.requirements import Requirement
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    declared = [*meta["dependencies"], *meta["optional-dependencies"]["geotiff"], *meta["optional-dependencies"]["dev"]]
    from_pyproject = {Requirement(r).name.lower(): str(Requirement(r).specifier) for r in declared}
    from_txt = {}
    for line in (ROOT / "requirements.txt").read_text("utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            req = Requirement(line)
            from_txt[req.name.lower()] = str(req.specifier)
    assert from_txt == from_pyproject


# ------------------------------------------------------------------------------------------------------------ fonts
@pytest.fixture(scope="module")
def qapp_():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_fonts_fall_back_to_what_the_machine_has(qapp_, monkeypatch):
    from PySide6.QtGui import QFontDatabase, QFontInfo
    from plumbline.ui import theme
    monkeypatch.setattr(QFontDatabase, "families", staticmethod(lambda *a, **k: ["Segoe UI", "Consolas", "Arial"]))   # a Windows box
    assert theme.mono_font().family() == "Consolas"
    assert theme.ui_font().pointSizeF() == pytest.approx(9.5)                       # no DejaVu: the system UI font, same size
    monkeypatch.setattr(QFontDatabase, "families", staticmethod(lambda *a, **k: []))
    assert QFontInfo(theme.mono_font(10)).fixedPitch()                              # nothing known: the system fixed-width font


def test_linux_keeps_dejavu(qapp_):
    from PySide6.QtGui import QFontDatabase
    from plumbline.ui import theme
    if "DejaVu Sans" not in QFontDatabase.families():
        pytest.skip("DejaVu fonts not installed here")
    assert theme.ui_font().family() == "DejaVu Sans"
    assert theme.mono_font().family() == "DejaVu Sans Mono"


# ------------------------------------------------------------------------------------------------- .bat launchers
@pytest.mark.parametrize("name", ["install_windows.bat", "Plumbline.bat"])
def test_windows_batch_files_are_ascii_with_crlf_line_endings(name):
    """cmd.exe misreads labels (goto) in LF-only files and garbles non-ASCII text, so keep these two properties."""
    data = (ROOT / name).read_bytes()
    data.decode("ascii")
    assert data.count(b"\n") == data.count(b"\r\n") > 10, "use Windows (CRLF) line endings"


def test_windows_batch_files_refer_to_things_that_exist():
    setup = (ROOT / "install_windows.bat").read_text("ascii")
    launcher = (ROOT / "Plumbline.bat").read_text("ascii")
    assert (ROOT / "requirements.txt").exists() and "requirements.txt" in setup
    assert (ROOT / "docs" / "WINDOWS_SETUP.md").exists()
    assert "Plumbline.bat" in setup and "install_windows.bat" in launcher
    for goto in ("nopython", "havevenv", "failed", "ready"):                          # every jump target is defined
        assert f":{goto}" in setup + launcher
    assert "-m plumbline doctor" in setup and "-m plumbline %*" in launcher
