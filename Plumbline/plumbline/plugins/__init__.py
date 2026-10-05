"""Plugin & script API.

Drop a ``.py`` file in your plugin folder (Plugins > Open plugin folder) and it is loaded at start-up
(or Plugins > Reload).  A plugin can add commands, importers and exporters::

    from plumbline.plugins import command, importer, exporter, Param

    @command("Tools/Round elevations", params=[Param("decimals", int, 2, "Decimal places")])
    def round_z(api, decimals=2):
        with api.edit("Round elevations"):
            for p in api.selected_points() or api.project.points.values():
                p.z = round(p.z, decimals)
        api.log("done")

``api`` is a :class:`PluginAPI`.  The same object is handed to scripts run with Plugins > Run script
(where ``project``, ``api``, ``np`` and the geometry/COGO modules are also in scope), so a script can
later be promoted to a plugin command unchanged.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import math
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ..core.settings import settings, user_dir


# ----------------------------------------------------------------------------- registry
@dataclass
class Param:
    """A command parameter; the UI builds an input dialog from these."""
    name: str
    type: type = float                 # int | float | str | bool
    default: object = None
    label: str = ""
    choices: list | None = None        # str with choices -> drop-down
    minimum: float | None = None
    maximum: float | None = None


@dataclass
class Command:
    path: str                          # "Menu/Sub/Name"
    func: object
    params: list = field(default_factory=list)
    description: str = ""
    shortcut: str | None = None
    source: str = ""

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def menu(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


@dataclass
class ImporterSpec:
    name: str
    extensions: list
    func: object
    source: str = ""


@dataclass
class ExporterSpec:
    name: str
    extension: str
    func: object
    source: str = ""


class _Registry:
    def __init__(self):
        self.commands: list[Command] = []
        self.importers: list[ImporterSpec] = []
        self.exporters: list[ExporterSpec] = []
        self.errors: list[tuple[str, str]] = []      # (file, traceback)
        self.loaded: list[str] = []
        self._source = ""

    def clear(self):
        self.commands.clear(); self.importers.clear(); self.exporters.clear()
        self.errors.clear(); self.loaded.clear()


registry = _Registry()


def command(path: str, params=(), description: str = "", shortcut: str | None = None):
    def deco(fn):
        registry.commands.append(Command(path, fn, list(params), description or (fn.__doc__ or "").strip(),
                                         shortcut, registry._source))
        return fn
    return deco


def importer(name: str, extensions):
    """Register an importer.  fn(path, api) must return a plumbline.core.model.ImportBatch."""
    def deco(fn):
        registry.importers.append(ImporterSpec(name, [e.lower() for e in extensions], fn, registry._source))
        return fn
    return deco


def exporter(name: str, extension: str):
    """Register an exporter.  fn(project, path, api) writes the file."""
    def deco(fn):
        registry.exporters.append(ExporterSpec(name, extension.lower(), fn, registry._source))
        return fn
    return deco


# ----------------------------------------------------------------------------- loading
def plugin_dir() -> Path:
    d = user_dir() / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def examples_dir() -> Path:
    return Path(__file__).parent / "examples"


def install_examples(overwrite: bool = False) -> list[str]:
    out = []
    for f in sorted(examples_dir().glob("*.py")):
        dst = plugin_dir() / f.name
        if overwrite or not dst.exists():
            dst.write_text(f.read_text("utf-8"), "utf-8")
            out.append(f.name)
    return out


def load_plugins(extra_dirs=()) -> list[tuple[str, str]]:
    """(Re)load every plugin file.  Errors are collected, never raised."""
    registry.clear()
    dirs = [plugin_dir()] + [Path(d) for d in settings().get("plugin_dirs") or []] + [Path(d) for d in extra_dirs]
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            modname = f"plumbline_plugin_{f.stem}"
            registry._source = str(f)
            n_before = (len(registry.commands), len(registry.importers), len(registry.exporters))
            try:
                spec = importlib.util.spec_from_file_location(modname, f)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[modname] = mod
                spec.loader.exec_module(mod)
                registry.loaded.append(str(f))
            except Exception:
                # roll back anything the half-loaded file registered
                del registry.commands[n_before[0]:]
                del registry.importers[n_before[1]:]
                del registry.exporters[n_before[2]:]
                registry.errors.append((str(f), traceback.format_exc()))
            finally:
                registry._source = ""
    return registry.errors


# ----------------------------------------------------------------------------- the API objects
class PluginAPI:
    """What plugins / scripts talk to.  Works with or without the GUI."""

    def __init__(self, project, state=None, log=None, ask=None, message=None):
        self.project = project
        self.state = state
        self._log = log or (lambda s: print(s))
        self._ask = ask
        self._message = message
        self.np = np
        from ..core import cogo, geometry, units
        self.cogo, self.geometry, self.units = cogo, geometry, units

    # ---- feedback
    def log(self, *args):
        self._log(" ".join(str(a) for a in args))

    def message(self, text: str, title: str = "Plumbline"):
        if self._message:
            self._message(title, text)
        else:
            print(f"[{title}] {text}")

    def ask(self, prompt: str, default: str = "") -> str | None:
        if self._ask:
            return self._ask(prompt, default)
        try:
            return input(f"{prompt} [{default}] ") or default
        except EOFError:
            return default

    # ---- editing (undo-aware when the GUI is attached)
    @contextlib.contextmanager
    def edit(self, label: str = "Script"):
        if self.state is not None:
            with self.state.edit(label):
                yield self.project
        else:
            try:
                yield self.project
            finally:
                self.project.touch()

    # ---- selection
    def selected_points(self):
        if self.state is None:
            return []
        return [self.project.points[i] for i in sorted(self.state.sel_points) if i in self.project.points]

    def selected_entities(self):
        if self.state is None:
            return []
        return [self.project.entities[i] for i in sorted(self.state.sel_entities) if i in self.project.entities]

    # ---- convenience
    def points(self):
        return list(self.project.points.values())

    def add_point(self, x, y, z=math.nan, desc="", number=None, layer=None):
        return self.project.add_point(x, y, z, number=number, desc=desc, layer=layer)

    def import_batch(self, batch, dup_policy: str = "renumber"):
        return self.project.apply_batch(batch, dup_policy)

    def refresh(self):
        if self.state is not None:
            self.state.refresh()


def run_script(path, project, state=None, log=None, ask=None, message=None) -> str | None:
    """Execute a Python file with the project in scope. Returns a traceback string on failure."""
    api = PluginAPI(project, state, log, ask, message)
    from ..core import cogo, geometry, units
    scope = {"__name__": "__plumbline_script__", "__file__": str(path), "project": project, "api": api,
             "np": np, "math": math, "G": geometry, "cogo": cogo, "U": units}
    code = Path(path).read_text("utf-8")
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(code, str(path), "exec"), scope)
        err = None
    except SystemExit:
        err = None
    except Exception:
        err = traceback.format_exc()
    text = out.getvalue()
    if text and log:
        for line in text.rstrip().splitlines():
            log(line)
    return err


def run_command(cmd: Command, api: PluginAPI, values: dict | None = None):
    """Call a command with defaults filled in from its Param list."""
    kw = {}
    for p in cmd.params:
        kw[p.name] = (values or {}).get(p.name, p.default)
    return cmd.func(api, **kw)
