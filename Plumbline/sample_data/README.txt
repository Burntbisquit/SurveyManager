SAMPLE DATA - everything here is SYNTHETIC (computer generated, not a real survey).
Regenerate with:   python -m plumbline sample sample_data

A small commercial lot with a street and a side street: gently rolling ground (a hill and a drainage swale),
edge-of-pavement strings with filleted corners, a centreline, sidewalk, building, parking lot, manhole / hydrant /
light poles / signs / trees, a fence, a closed property line, and ~100 ground shots.
Coordinates are NAD83 / Texas North Central (US ft, EPSG:2276) near Mesquite, TX only so the CRS tools and imagery
have somewhere plausible to land.  Assign a different system in the app to move it anywhere.

  sample_points_PNEZD.csv     238 points, no header:   Point, Northing, Easting, Elevation, Description
  sample_points_XYZ_tab.txt   same points, tab separated WITH a header, X (easting) before Y - tests column mapping
  sample_site.dxf             points + labels, linework (with arcs), contours-free plan
  sample_site.xml             LandXML 1.2: CgPoints, a TIN surface, linework
  sample_site.gpkg            GeoPackage with points / lines / polygons layers (EPSG:2276)
  sample_site.kmz             Google Earth file (WGS84 lon/lat) - try File > Import, or open it in Google Earth
  sample_site.plb             the Plumbline project itself

Things planted for you to find:
  * point 186 (a GS shot) has a +4.9 ft elevation "bust" - Survey > Data Quality Check finds it, and you can see it as a
    tight cluster of contours once you build a surface.
  * description codes use the starter feature-code table: EP1 B / EP1 / EP1 E start, continue and end a string; PL1 ... CLS closes
    the property line; BLDG is a closed polygon; MH, SSMH, FH, LP, SIGN, TREE are point symbols not used for the ground surface.
