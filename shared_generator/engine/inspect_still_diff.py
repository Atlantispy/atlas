from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

from source_catalogue import source_path

parent = source_path("terrain_d31_100m")
local = source_path("stillklinge_terrain_100m")
with rasterio.open(parent) as p, rasterio.open(local) as s:
    window = from_bounds(*s.bounds, transform=p.transform).round_offsets().round_lengths()
    a = p.read(1, window=window)
    b = s.read(1)
    d = np.abs(a - b)
    changed = d > 1e-5
    rows, cols = np.where(changed)
    print({
        "parent_window": [window.row_off, window.col_off, window.height, window.width],
        "changed_cells": int(changed.sum()),
        "changed_fraction": float(changed.mean()),
        "max_abs_difference_m": float(d.max()),
        "changed_local_bbox_cells": [int(rows.min()), int(cols.min()), int(rows.max()), int(cols.max())] if len(rows) else None,
        "changed_global_bbox_km": [
            float(s.transform.c + cols.min() * 0.1), float(s.transform.f + rows.min() * 0.1),
            float(s.transform.c + (cols.max() + 1) * 0.1), float(s.transform.f + (rows.max() + 1) * 0.1),
        ] if len(rows) else None,
    })
