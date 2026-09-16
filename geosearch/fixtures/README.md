# Bern park regression fixture

`bern-parks-2026-09-11.json.gz` contains unmodified geometry fetched on 2026-09-11
from the official geo.admin.ch identify API: `ch.bafu.schutzgebiete-paerke_nationaler_bedeutung`
and the latest published `ch.swisstopo.swissboundaries3d-kanton-flaeche.fill` boundary
for Bern. Attribution: BAFU / swisstopo / geo.admin.ch.

Nine bounding-box candidates include eight objects intersecting/touching Bern
(15, 18, 19, 20, 21, 22, 23, 25) and Binntal (16) outside. Geometry is not simplified:
tiny overlaps and Gruyère's invalid polygon are necessary to reproduce the failure.
Use intersection selection for the eight full objects. Clipping alone deliberately
excludes Pfyn-Finges under its sliver policy; repaired clipping yields seven.
