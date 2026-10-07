SAMPLE DATA - everything here is SYNTHETIC (computer generated, not a real survey).
Regenerate with:   python -m plumbline sample sample_data

A small commercial lot with a street and a side street: gently rolling ground (a hill and a drainage swale),
asphalt edges with filleted corners, a centerline, sidewalk, building, parking lot, utilities, trees, and a fence.
Descriptions use Carlson Field-to-Finish conventions represented by the shipped Carlson F2F reference:
line-start / line-end commands, a close command for closed features, and a description separator for notes
(e.g. T14 / OAK). The project's Field Book code table is synthetic and built from representative F2F codes.

Coordinates are NAD83(2011) / Texas North Central (US survey feet, EPSG:6584) near Mesquite, TX only so the
CRS tools and imagery have somewhere plausible to land. Assign a different system in the app to move it anywhere.

  sample_points_PNEZD.csv     238 points, no header: Point, Northing, Easting, Elevation, Description
  sample_points_XYZ_tab.txt   same points, tab separated WITH a header, X (easting) before Y - tests column mapping
  sample_site.dxf             points + labels, linework (with arcs), contours-free plan
  sample_site.xml             LandXML 1.2: CgPoints, a TIN surface, linework
  sample_site.gpkg            GeoPackage with points / lines / polygons layers (EPSG:6584)
  sample_site.kmz             Google Earth file (WGS84 lon/lat) - try File > Import, or open it in Google Earth
  sample_site.plb             the Plumbline project itself

Things planted for you to find:
  * point 186 (an NG natural-ground shot) has a +4.9 ft elevation bust - Survey > Data Quality Check finds it, and
    the elevated shot is visible in the surface and contours.
  * Carlson-style descriptions encode edge/centerline/sidewalk linework, a closed building/fence feature,
    representative utility and tree codes, and code-plus-note descriptions. The synthetic Field Book records the
    corresponding code meanings and linework command semantics.
  * the project remains synthetic; the files in samples/Real World are separate real-world survey data and are not
    regenerated or edited by this sample builder.
