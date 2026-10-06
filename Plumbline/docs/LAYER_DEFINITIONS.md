# Field Book Sister Specification: Layer Definitions, Colors, Linestyles & Symbology

This specification serves as the official **sister document to Field Book (`.fwb` / F2F)** in Plumbline. It defines how field codes map to CAD drawing layers with authoritative RGB colors, linestyles, and symbology conventions.

---

## 1. Overview & Architecture

When field data is processed through the Field Book:
1. **Empty Layer Startup**: Projects start without hard-coded pre-seeded layers.
2. **Dynamic Layer Creation**: When points, lines, or boundaries are reduced through the Field Book, each referenced layer is automatically populated using the sister layer definitions.
3. **Layer Attributes**: Each layer receives its authoritative color, CAD linetype, symbology type, and category classification.

---

## 2. Standard Layer Definitions Table

| Layer Name | Category | Color (RGB) | Linestyle | Symbology Type | Description |
|:---|:---|:---|:---|:---|:---|
| `CONTROL-BM` | Control | `(255, 90, 90)` | `CONTINUOUS` | `triangle` | Benchmark control points |
| `CONTROL-CP` | Control | `(255, 90, 90)` | `CONTINUOUS` | `triangle` | Control points / traverse stations |
| `CONTROL-GPS` | Control | `(255, 60, 60)` | `CONTINUOUS` | `triangle` | GPS control points |
| `BNDY-PL` | Boundary | `(255, 255, 255)` | `PHANTOM` | `square` | Property / lot boundary lines |
| `BNDY-ROW` | Boundary | `(255, 120, 120)` | `PHANTOM` | `square` | Right of way lines |
| `BNDY-EASE` | Boundary | `(180, 120, 255)` | `HIDDEN` | `square` | Easement boundary lines |
| `V-PROP-CRNR` | Boundary | `(255, 255, 255)` | `CONTINUOUS` | `square` | Property corner monument nodes |
| `TOPO-GROUND` | Topo | `(200, 200, 200)` | `CONTINUOUS` | `cross` | Ground elevation topography points |
| `TOPO-SPOT` | Topo | `(200, 200, 200)` | `CONTINUOUS` | `cross` | Spot elevation topography points |
| `ROAD-EP` | Roads | `(255, 255, 0)` | `CONTINUOUS` | `circle` | Edge of pavement |
| `ROAD-CURB-TOP` | Roads | `(255, 190, 0)` | `CONTINUOUS` | `circle` | Top of curb |
| `ROAD-CURB-BACK` | Roads | `(255, 150, 0)` | `CONTINUOUS` | `circle` | Back of curb |
| `ROAD-FL` | Roads | `(0, 200, 255)` | `CONTINUOUS` | `circle` | Flowline / gutter |
| `ROAD-CL` | Roads | `(255, 0, 255)` | `CENTER` | `circle` | Centreline of road |
| `ROAD-GRAVEL` | Roads | `(200, 160, 100)` | `DASHED` | `point` | Edge of gravel / dirt road |
| `ROAD-SIDEWALK` | Roads | `(190, 190, 190)` | `CONTINUOUS` | `circle` | Sidewalk pavement edge |
| `ROAD-DRIVE` | Roads | `(170, 170, 255)` | `CONTINUOUS` | `circle` | Driveway pavement edge |
| `STRUCT-BLDG` | Structures | `(255, 128, 0)` | `CONTINUOUS` | `square` | Building outline / foundation |
| `STRUCT-FFE` | Structures | `(255, 128, 0)` | `CONTINUOUS` | `square` | Finished floor elevation |
| `STRUCT-WALL` | Structures | `(220, 120, 60)` | `CONTINUOUS` | `square` | Retaining / structural wall |
| `SITE-FENCE` | Site | `(140, 255, 140)` | `DASHDOT` | `plus` | Fence lines |
| `SITE-SIGN` | Site | `(255, 255, 120)` | `CONTINUOUS` | `diamond` | Traffic and site signs |
| `UTIL-MH` | Utilities | `(0, 255, 255)` | `CONTINUOUS` | `circle` | Manholes (general) |
| `UTIL-SS` | Utilities | `(0, 220, 0)` | `CONTINUOUS` | `circle` | Sanitary sewer linework & structures |
| `UTIL-SD` | Utilities | `(0, 180, 255)` | `CONTINUOUS` | `circle` | Storm drain linework & inlets |
| `UTIL-WATER` | Utilities | `(80, 140, 255)` | `CONTINUOUS` | `circle` | Water lines, valves, and hydrants |
| `UTIL-POWER` | Utilities | `(255, 100, 255)` | `CONTINUOUS` | `diamond` | Power / electrical lines |
| `UTIL-OHE` | Utilities | `(255, 100, 255)` | `DASHDOT` | `diamond` | Overhead electric lines |
| `UTIL-GAS` | Utilities | `(255, 200, 0)` | `DASHED` | `diamond` | Gas pipeline & valves |
| `UTIL-COMM` | Utilities | `(255, 140, 0)` | `DASHED` | `diamond` | Telecommunication / fiber optics |
| `HYDRO-CREEK` | Hydro | `(0, 140, 255)` | `CONTINUOUS` | `point` | Creek / stream centreline |
| `HYDRO-BANK-TOP` | Hydro | `(120, 200, 120)` | `CONTINUOUS` | `point` | Top of bank |
| `HYDRO-BANK-BOT` | Hydro | `(60, 170, 220)` | `CONTINUOUS` | `point` | Bottom of bank |
| `HYDRO-SWALE` | Hydro | `(0, 220, 200)` | `CONTINUOUS` | `point` | Drainage swale |
| `VEG-TREE` | Vegetation | `(40, 200, 60)` | `CONTINUOUS` | `circle` | Trees, palms, and landscaping |
| `VEG-BRUSH` | Vegetation | `(40, 160, 60)` | `DASHED` | `cross` | Tree line and heavy brush |
| `CONTOUR-MINOR` | Contours | `(150, 110, 60)` | `CONTINUOUS` | `none` | Minor elevation contours |
| `CONTOUR-INDEX` | Contours | `(230, 160, 70)` | `CONTINUOUS` | `none` | Index elevation contours |
| `CONTOUR-LABEL` | Contours | `(255, 220, 160)` | `CONTINUOUS` | `none` | Contour elevation text |

---

## 3. Linestyle Rules
- **`CONTINUOUS`**: Solid lines used for physical features (curbs, pavements, structures, utilities, topo).
- **`PHANTOM`**: Long dash - short dash - short dash, used for legal property and right-of-way boundaries.
- **`HIDDEN`**: Uniform short dashed line, used for underground features, easements, and obscured objects.
- **`CENTER`**: Long dash - short dash, used for roadway and corridor centrelines.
- **`DASHDOT`**: Dash - dot pattern, used for fences, property boundaries, and overhead utility lines.

---

## 4. Symbology Conventions
- **`triangle`**: Used for primary reference points (BM, CP, GPS control).
- **`square`**: Used for boundary corners, iron rods, monuments, and buildings.
- **`circle`**: Used for utility nodes (manholes, valves, poles) and trees.
- **`cross` / `plus`**: Used for spot elevations, fences, and general topo shots.
- **`diamond`**: Used for utility crossings, overhead lines, and signs.
- **`point`**: Default minimal vertex marker.
