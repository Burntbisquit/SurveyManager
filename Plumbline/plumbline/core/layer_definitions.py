"""Sister specification to Field Book: authoritative definitions for layer colors, linestyles, and symbology."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .model import Layer


@dataclass
class LayerDefinition:
    """Authoritative layer definition linking Field Book codes to CAD styling and symbology."""
    name: str
    color: tuple[int, int, int]
    linetype: str = "CONTINUOUS"
    symbology: str = "point"
    description: str = ""
    category: str = "General"
    default_visible: bool = True
    default_locked: bool = False

    def to_layer(self) -> Layer:
        return Layer(
            name=self.name,
            color=self.color,
            linetype=self.linetype,
            visible=self.default_visible,
            locked=self.default_locked,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "color": list(self.color),
            "linetype": self.linetype,
            "symbology": self.symbology,
            "description": self.description,
            "category": self.category,
            "default_visible": self.default_visible,
            "default_locked": self.default_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayerDefinition:
        c = data.get("color", [255, 255, 255])
        color_tuple = (int(c[0]), int(c[1]), int(c[2])) if isinstance(c, (list, tuple)) and len(c) >= 3 else (255, 255, 255)
        return cls(
            name=str(data.get("name", "")),
            color=color_tuple,
            linetype=str(data.get("linetype", "CONTINUOUS")),
            symbology=str(data.get("symbology", "point")),
            description=str(data.get("description", "")),
            category=str(data.get("category", "General")),
            default_visible=bool(data.get("default_visible", True)),
            default_locked=bool(data.get("default_locked", False)),
        )


# Authoritative Standard Layer Definitions Table
STANDARD_LAYER_DEFINITIONS: dict[str, LayerDefinition] = {
    # Control
    "CONTROL-BM": LayerDefinition("CONTROL-BM", (255, 90, 90), "CONTINUOUS", "triangle", "Benchmark control points", "Control"),
    "CONTROL-CP": LayerDefinition("CONTROL-CP", (255, 90, 90), "CONTINUOUS", "triangle", "Control points / traverse stations", "Control"),
    "CONTROL-GPS": LayerDefinition("CONTROL-GPS", (255, 60, 60), "CONTINUOUS", "triangle", "GPS control points", "Control"),
    "V-NODE-CTRL": LayerDefinition("V-NODE-CTRL", (255, 90, 90), "CONTINUOUS", "triangle", "Carlson Control Nodes", "Control"),

    # Boundary & Property
    "BNDY-PL": LayerDefinition("BNDY-PL", (255, 255, 255), "PHANTOM", "square", "Property / lot lines", "Boundary"),
    "BNDY-ROW": LayerDefinition("BNDY-ROW", (255, 120, 120), "PHANTOM", "square", "Right of way lines", "Boundary"),
    "BNDY-EASE": LayerDefinition("BNDY-EASE", (180, 120, 255), "HIDDEN", "square", "Easement lines", "Boundary"),
    "V-PROP-CRNR": LayerDefinition("V-PROP-CRNR", (255, 255, 255), "CONTINUOUS", "square", "Property corner monuments", "Boundary"),
    "V-PROP-LINE": LayerDefinition("V-PROP-LINE", (255, 255, 255), "PHANTOM", "none", "Property line linework", "Boundary"),

    # Topo & Ground
    "TOPO-GROUND": LayerDefinition("TOPO-GROUND", (200, 200, 200), "CONTINUOUS", "cross", "Ground elevation topography shots", "Topo"),
    "TOPO-SPOT": LayerDefinition("TOPO-SPOT", (200, 200, 200), "CONTINUOUS", "cross", "Spot elevation topography points", "Topo"),
    "POINTS": LayerDefinition("POINTS", (255, 255, 255), "CONTINUOUS", "point", "Default loose survey points", "General"),
    "0": LayerDefinition("0", (230, 230, 230), "CONTINUOUS", "none", "Standard AutoCAD base layer", "General"),

    # Roads & Pavement
    "ROAD-EP": LayerDefinition("ROAD-EP", (255, 255, 0), "CONTINUOUS", "circle", "Edge of pavement", "Roads"),
    "ROAD-CURB-TOP": LayerDefinition("ROAD-CURB-TOP", (255, 190, 0), "CONTINUOUS", "circle", "Top of curb", "Roads"),
    "ROAD-CURB-BACK": LayerDefinition("ROAD-CURB-BACK", (255, 150, 0), "CONTINUOUS", "circle", "Back of curb", "Roads"),
    "ROAD-FL": LayerDefinition("ROAD-FL", (0, 200, 255), "CONTINUOUS", "circle", "Flowline / gutter", "Roads"),
    "ROAD-CL": LayerDefinition("ROAD-CL", (255, 0, 255), "CENTER", "circle", "Centreline of road", "Roads"),
    "ROAD-GRAVEL": LayerDefinition("ROAD-GRAVEL", (200, 160, 100), "DASHED", "point", "Edge of gravel / dirt road", "Roads"),
    "ROAD-SIDEWALK": LayerDefinition("ROAD-SIDEWALK", (190, 190, 190), "CONTINUOUS", "circle", "Sidewalk pavement edge", "Roads"),
    "ROAD-DRIVE": LayerDefinition("ROAD-DRIVE", (170, 170, 255), "CONTINUOUS", "circle", "Driveway pavement edge", "Roads"),
    "V-ROAD-PVD": LayerDefinition("V-ROAD-PVD", (255, 255, 0), "CONTINUOUS", "circle", "Paved roadway edges", "Roads"),
    "V-ROAD-CURB": LayerDefinition("V-ROAD-CURB", (255, 190, 0), "CONTINUOUS", "circle", "Roadway curb lines", "Roads"),

    # Structures & Site
    "STRUCT-BLDG": LayerDefinition("STRUCT-BLDG", (255, 128, 0), "CONTINUOUS", "square", "Building outline", "Structures"),
    "STRUCT-FFE": LayerDefinition("STRUCT-FFE", (255, 128, 0), "CONTINUOUS", "square", "Finished floor elevation", "Structures"),
    "STRUCT-WALL": LayerDefinition("STRUCT-WALL", (220, 120, 60), "CONTINUOUS", "square", "Retaining / foundation wall", "Structures"),
    "STRUCT-RW": LayerDefinition("STRUCT-RW", (220, 120, 60), "CONTINUOUS", "square", "Retaining wall face", "Structures"),
    "SITE-FENCE": LayerDefinition("SITE-FENCE", (140, 255, 140), "DASHDOT", "plus", "Fence lines", "Site"),
    "SITE-SIGN": LayerDefinition("SITE-SIGN", (255, 255, 120), "CONTINUOUS", "diamond", "Site & traffic signs", "Site"),
    "V-BLDG": LayerDefinition("V-BLDG", (255, 128, 0), "CONTINUOUS", "square", "Building lines", "Structures"),
    "V-SITE-FENC": LayerDefinition("V-SITE-FENC", (140, 255, 140), "DASHDOT", "plus", "Fence linework", "Site"),

    # Utilities
    "UTIL-MH": LayerDefinition("UTIL-MH", (0, 255, 255), "CONTINUOUS", "circle", "Manholes (general)", "Utilities"),
    "UTIL-SS": LayerDefinition("UTIL-SS", (0, 220, 0), "CONTINUOUS", "circle", "Sanitary sewer", "Utilities"),
    "UTIL-SD": LayerDefinition("UTIL-SD", (0, 180, 255), "CONTINUOUS", "circle", "Storm drain", "Utilities"),
    "UTIL-WATER": LayerDefinition("UTIL-WATER", (80, 140, 255), "CONTINUOUS", "circle", "Water line & valves", "Utilities"),
    "UTIL-POWER": LayerDefinition("UTIL-POWER", (255, 100, 255), "CONTINUOUS", "diamond", "Power / electrical lines", "Utilities"),
    "UTIL-OHE": LayerDefinition("UTIL-OHE", (255, 100, 255), "DASHDOT", "diamond", "Overhead electric", "Utilities"),
    "UTIL-GAS": LayerDefinition("UTIL-GAS", (255, 200, 0), "DASHED", "diamond", "Gas line & valves", "Utilities"),
    "UTIL-COMM": LayerDefinition("UTIL-COMM", (255, 140, 0), "DASHED", "diamond", "Telecommunication / fiber", "Utilities"),
    "E_Utility_Electric_LightPole": LayerDefinition("E_Utility_Electric_LightPole", (255, 200, 100), "CONTINUOUS", "circle", "Light poles", "Utilities"),
    "E_Utility_Cable": LayerDefinition("E_Utility_Cable", (255, 140, 0), "DASHED", "diamond", "Underground cable", "Utilities"),

    # Hydrography & Drainage
    "HYDRO-CREEK": LayerDefinition("HYDRO-CREEK", (0, 140, 255), "CONTINUOUS", "point", "Creek / stream centreline", "Hydro"),
    "HYDRO-BANK-TOP": LayerDefinition("HYDRO-BANK-TOP", (120, 200, 120), "CONTINUOUS", "point", "Top of bank", "Hydro"),
    "HYDRO-BANK-BOT": LayerDefinition("HYDRO-BANK-BOT", (60, 170, 220), "CONTINUOUS", "point", "Bottom of bank", "Hydro"),
    "HYDRO-WATEREDGE": LayerDefinition("HYDRO-WATEREDGE", (80, 180, 255), "CONTINUOUS", "point", "Water edge / pond", "Hydro"),
    "HYDRO-SWALE": LayerDefinition("HYDRO-SWALE", (0, 220, 200), "CONTINUOUS", "point", "Drainage swale", "Hydro"),

    # Grade & Breaklines
    "GRADE-TOS": LayerDefinition("GRADE-TOS", (160, 255, 80), "CONTINUOUS", "point", "Top of slope", "Grade"),
    "GRADE-TOE": LayerDefinition("GRADE-TOE", (255, 160, 80), "CONTINUOUS", "point", "Toe of slope", "Grade"),

    # Vegetation
    "VEG-TREE": LayerDefinition("VEG-TREE", (40, 200, 60), "CONTINUOUS", "circle", "Trees & palms", "Vegetation"),
    "VEG-BRUSH": LayerDefinition("VEG-BRUSH", (40, 160, 60), "DASHED", "cross", "Brush & tree line", "Vegetation"),
    "V-NODE-TREE": LayerDefinition("V-NODE-TREE", (40, 200, 60), "CONTINUOUS", "circle", "Tree points", "Vegetation"),

    # Contours & Surfaces
    "CONTOUR-MINOR": LayerDefinition("CONTOUR-MINOR", (150, 110, 60), "CONTINUOUS", "none", "Minor surface contours", "Contours"),
    "CONTOUR-INDEX": LayerDefinition("CONTOUR-INDEX", (230, 160, 70), "CONTINUOUS", "none", "Index surface contours", "Contours"),
    "CONTOUR-LABEL": LayerDefinition("CONTOUR-LABEL", (255, 220, 160), "CONTINUOUS", "none", "Contour elevation labels", "Contours"),
}


def get_layer_definition(layer_name: str, fallback_color=(200, 200, 200)) -> LayerDefinition:
    """Retrieve the authoritative LayerDefinition for a layer name, with fuzzy category fallback."""
    if not layer_name:
        return LayerDefinition("0", (230, 230, 230))

    if layer_name in STANDARD_LAYER_DEFINITIONS:
        return STANDARD_LAYER_DEFINITIONS[layer_name]

    # Prefix / substring heuristics
    u = layer_name.upper()
    if any(k in u for k in ("CTRL", "BM", "CP", "BENCH", "CONTROL")):
        return LayerDefinition(layer_name, (255, 90, 90), "CONTINUOUS", "triangle", "", "Control")
    if any(k in u for k in ("BNDY", "PROP", "LOT", "EASE", "ROW", "SECTION")):
        return LayerDefinition(layer_name, (255, 255, 255), "PHANTOM", "square", "", "Boundary")
    if any(k in u for k in ("ROAD", "PAVE", "CURB", "DRIVE", "WALK", "ASPH")):
        return LayerDefinition(layer_name, (255, 255, 0), "CONTINUOUS", "circle", "", "Roads")
    if any(k in u for k in ("BLDG", "STRUCT", "WALL", "FENCE", "DECK")):
        return LayerDefinition(layer_name, (255, 128, 0), "CONTINUOUS", "square", "", "Structures")
    if any(k in u for k in ("UTIL", "SEW", "STM", "WAT", "ELEC", "GAS", "COMM", "POLE")):
        return LayerDefinition(layer_name, (0, 255, 255), "CONTINUOUS", "circle", "", "Utilities")
    if any(k in u for k in ("HYDRO", "CREEK", "POND", "SWALE", "DRAIN", "WATER")):
        return LayerDefinition(layer_name, (0, 180, 255), "CONTINUOUS", "point", "", "Hydro")
    if any(k in u for k in ("TREE", "VEG", "BRUSH", "BUSH")):
        return LayerDefinition(layer_name, (40, 200, 60), "CONTINUOUS", "circle", "", "Vegetation")
    if any(k in u for k in ("TOPO", "GROUND", "SPOT", "ELEV")):
        return LayerDefinition(layer_name, (200, 200, 200), "CONTINUOUS", "cross", "", "Topo")

    return LayerDefinition(layer_name, fallback_color, "CONTINUOUS", "point", "", "General")


def populate_layers_from_fieldbook(project, fieldbook_codes=None) -> list[str]:
    """Ensure all layers referenced by the Field Book exist in project with authoritative colors and linestyles."""
    codes = fieldbook_codes if fieldbook_codes is not None else getattr(project, "codes", {})
    codes_values = list(codes.values()) if hasattr(codes, "values") else list(codes) if isinstance(codes, (list, tuple)) else []
    created = []

    for fc in codes_values:
        layer_name = getattr(fc, "layer", None)
        if not layer_name:
            continue
        if layer_name not in project.layers:
            ld = get_layer_definition(layer_name)
            # Use sister definition color / linetype, or explicit code override if non-white
            fc_color = getattr(fc, "color", None)
            col = fc_color if fc_color and fc_color != (255, 255, 255) else ld.color
            fc_lt = getattr(fc, "linetype", None)
            lt = fc_lt if fc_lt and fc_lt != "CONTINUOUS" else ld.linetype
            project.ensure_layer(layer_name, col, lt)
            created.append(layer_name)

    return created


def export_sister_layer_document(path: Path | str, definitions: dict[str, LayerDefinition] | None = None) -> Path:
    """Export sister layer definitions to a JSON document."""
    defs = definitions or STANDARD_LAYER_DEFINITIONS
    out = {k: v.to_dict() for k, v in sorted(defs.items())}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return p


def import_sister_layer_document(path: Path | str) -> dict[str, LayerDefinition]:
    """Import sister layer definitions from a JSON document."""
    p = Path(path)
    if not p.exists():
        return dict(STANDARD_LAYER_DEFINITIONS)
    data = json.loads(p.read_text(encoding="utf-8"))
    res = {}
    for k, v in data.items():
        if isinstance(v, dict):
            res[k] = LayerDefinition.from_dict(v)
    return res
